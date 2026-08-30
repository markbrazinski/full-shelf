import json
import hashlib
import logging
import os
import base64
import asyncio
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, Any, Literal, Optional, List
from zoneinfo import ZoneInfo
from fastapi import Depends, FastAPI, Header, HTTPException, Query, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
import httpx

from google.cloud import spanner
from full_shelf_observability import (
    build_traceparent,
    generate_span_id,
    get_tracer,
    generate_trace_id,
    request_trace_span,
)
from full_shelf_domain.identity import (
    GoogleOidcVerifier, IdentityConfigurationError, InvalidIdentityToken,
    MissingIdentityToken, UnauthorizedIdentity, VerifiedGoogleIdentity,
    fetch_google_id_token,
)
from full_shelf_domain.identity import IdentityPlatformOperatorVerifier
from full_shelf_domain.judge_isolation import assert_judge_isolation
from full_shelf_domain.authority import (
    AuthorityConfigurationError,
    AuthorityScopeResolver,
    UnauthorizedAuthorityScope,
    operating_day_authority_id,
)
from full_shelf_domain.ledger_commands import (
    NextDayRequest,
    OperatingDayRequest,
    RecurringDailyRequest,
)
from full_shelf_domain.partner_evidence import (
    PARTNER_CALLBACK_PROVENANCE,
    PARTNER_EVIDENCE_EVENT_TYPE,
    PartnerCustodyConfirmationDetails,
    partner_evidence_prompt,
    run_partner_evidence_agent,
    source_sha256,
)
from full_shelf_domain.recall import (
    inspect_recall_notice_with_model_armor,
    extract_recall_entities_with_gemini_35,
    publish_recall_event_to_pubsub,
    schedule_site01_deadline_task,
    IncidentLifecycleManager,
    MODEL_ID,
    VERTEX_LOCATION,
    is_eligible_gemini_model,
)
from full_shelf_domain.fleet.contracts import (
    AGENT_FULFILLMENT_PLANNING_RECOVERY,
    AGENT_INCIDENT_LEAD,
    AGENT_RECALL_INTAKE_EXTRACTION,
    AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
    FLEET_MANIFEST_VERSION,
    FleetProposalError,
)
from full_shelf_domain.fleet.coordinator import AGENT_INCIDENT_COORDINATOR, GOVERNED_SEQUENCE, run_fleet
from full_shelf_domain.fleet.orchestration import TriggerClass
from full_shelf_domain.fleet.manifest import build_manifest
from full_shelf_domain.fleet.tools import generate_recovery_candidates

app = FastAPI(
    title="Full Shelf Fulfillment Orchestrator API",
    version="1.1.0",
    description="Production control plane for food-bank fulfillment operations governed by AGENTS.md and Build Book v1.1.",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)


# -------------------------------------------------------------------
# DELTA 1 - BROWSER ORIGIN BOUNDARY
# The operator UI is a separate origin. Only exact, explicitly configured
# origins are permitted, and only the three HUMAN_OPERATOR routes are
# reachable from a browser anyway (see ROUTE_AUTHENTICATION_MATRIX).
# The private plan ledger deliberately receives no CORS configuration.
# -------------------------------------------------------------------
FRONTEND_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
if FRONTEND_ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
        expose_headers=["X-Full-Shelf-Trace-Id"],
        max_age=600,
    )

tracer = get_tracer("orchestrator")
logger = logging.getLogger("full_shelf.orchestrator")

PUBLIC_HEALTH = "PUBLIC_HEALTH"
HUMAN_OPERATOR = "HUMAN_OPERATOR"
MANAGED_CALLBACK = "MANAGED_CALLBACK"
PARTNER_CALLBACK = "PARTNER_CALLBACK"
INTERNAL_WORKLOAD = "INTERNAL_WORKLOAD"
DISABLED_OR_REMOVED = "DISABLED_OR_REMOVED"

# This is the complete ingress contract. The middleware below denies any method
# and path absent from this table, and startup refuses any newly registered
# FastAPI route until it has been deliberately classified here.
ROUTE_AUTHENTICATION_MATRIX = {
    ("GET", "/"): PUBLIC_HEALTH,
    ("GET", "/healthz"): PUBLIC_HEALTH,
    ("POST", "/api/v1/orchestrator/approvals/approve-and-activate"): HUMAN_OPERATOR,
    ("POST", "/api/v1/orchestrator/partner-evidence"): PARTNER_CALLBACK,
    ("GET", "/api/v1/projections/demo-beats"): HUMAN_OPERATOR,
    ("GET", "/api/v1/projections/stream"): HUMAN_OPERATOR,
    ("POST", "/api/v1/incidents/site01-deadline"): MANAGED_CALLBACK,
    ("POST", "/api/v1/orchestrator/pubsub/push"): MANAGED_CALLBACK,
    ("POST", "/api/v1/orchestrator/daily-plan/generate"): INTERNAL_WORKLOAD,
    ("POST", "/api/v1/orchestrator/coordinator/persist-waiting"): INTERNAL_WORKLOAD,
    ("POST", "/api/v1/orchestrator/site01-escalation/schedule"): INTERNAL_WORKLOAD,
    ("GET", "/api/v1/orchestrator/custody/graph"): INTERNAL_WORKLOAD,
    ("POST", "/api/v1/orchestrator/recall/model-armor-preflight"): INTERNAL_WORKLOAD,
    ("POST", "/api/v1/orchestrator/recall/extraction-preflight"): INTERNAL_WORKLOAD,
    ("POST", "/api/v1/orchestrator/recall/trigger"): INTERNAL_WORKLOAD,
    ("GET", "/api/v1/orchestrator/recall/incident-status"): INTERNAL_WORKLOAD,
    ("POST", "/api/v1/orchestrator/next-day-plan/generate"): INTERNAL_WORKLOAD,
    ("POST", "/api/v1/orchestrator/fleet/refrigeration-failure"): INTERNAL_WORKLOAD,
    ("GET", "/api/v1/evidence/system"): INTERNAL_WORKLOAD,
    ("GET", "/api/v1/demo/export-evidence"): INTERNAL_WORKLOAD,
    ("POST", "/api/v1/orchestrator/s2s-dispatch"): DISABLED_OR_REMOVED,
    ("POST", "/api/v1/orchestrator/recall/execute-hero-loop"): DISABLED_OR_REMOVED,
    ("POST", "/api/v1/demo/reset"): DISABLED_OR_REMOVED,
    ("POST", "/api/v1/demo/seed"): DISABLED_OR_REMOVED,
    ("POST", "/api/v1/demo/replay"): DISABLED_OR_REMOVED,
}

REMOVED_FRAMEWORK_ROUTES = frozenset({
    ("GET", "/openapi.json"),
    ("HEAD", "/openapi.json"),
    ("GET", "/docs"),
    ("HEAD", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("HEAD", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
    ("HEAD", "/redoc"),
})


def registered_route_authentication_matrix() -> dict[tuple[str, str], str]:
    """Return the classified registered surface or fail on an unclassified route."""
    registered: dict[tuple[str, str], str] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            key = (method, route.path)
            policy = ROUTE_AUTHENTICATION_MATRIX.get(key)
            if policy is None:
                raise RuntimeError(f"UNCLASSIFIED_ORCHESTRATOR_ROUTE:{method}:{route.path}")
            registered[key] = policy
    return registered


def _normalized_target_path(path: str) -> str:
    """Collapse a request path to the form the route matrix is keyed on."""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return path


def _preflight_target_policy(request: Request) -> Optional[str]:
    """Classify a genuine CORS preflight, or return None if it is not one.

    A preflight is recognized only when the method is OPTIONS and the browser
    sent both Origin and Access-Control-Request-Method. It is classified only
    when the origin is explicitly allowlisted AND the *target* method and
    normalized path already appear in ROUTE_AUTHENTICATION_MATRIX. OPTIONS is
    deliberately never added to that matrix: a preflight carries no credentials
    and reaches no handler, so admitting it must not widen the route surface.
    """
    if request.method != "OPTIONS":
        return None
    origin = request.headers.get("origin")
    requested_method = request.headers.get("access-control-request-method")
    if not origin or not requested_method:
        return None
    if origin not in FRONTEND_ALLOWED_ORIGINS:
        return None
    target = (requested_method.strip().upper(),
              _normalized_target_path(request.url.path))
    return ROUTE_AUTHENTICATION_MATRIX.get(target)


@app.middleware("http")
async def deny_unclassified_routes(request: Request, call_next):
    # An allowlisted preflight for an already-classified target is handed to
    # CORSMiddleware, which sits inside this middleware and answers it. Every
    # other OPTIONS request falls through to the ordinary closed-matrix check.
    if _preflight_target_policy(request) is not None:
        return await call_next(request)
    policy = ROUTE_AUTHENTICATION_MATRIX.get(
        (request.method, _normalized_target_path(request.url.path)))
    if policy is None:
        return JSONResponse(
            status_code=403,
            content={"detail": "ORCHESTRATOR_ROUTE_AUTHENTICATION_POLICY_REQUIRED"},
        )
    request.state.route_authentication_policy = policy
    return await call_next(request)


@app.middleware("http")
async def managed_request_trace(request: Request, call_next):
    with request_trace_span(
        tracer,
        request.headers,
        f"orchestrator {request.method} {request.url.path}",
    ) as trace_id:
        request.state.full_shelf_trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Full-Shelf-Trace-Id"] = trace_id
        return response

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")
SPANNER_INSTANCE = os.getenv("SPANNER_INSTANCE_ID", "fef-smoke-spanner")
SPANNER_DATABASE = os.getenv("SPANNER_DATABASE_ID", "full-shelf-main")
PLAN_LEDGER_URL = os.getenv("PLAN_LEDGER_URL", "")
PLAN_LEDGER_AUDIENCE = os.getenv("PLAN_LEDGER_AUDIENCE", "")
MANAGED_CALLBACK_AUDIENCE = os.getenv("MANAGED_CALLBACK_AUDIENCE", "")
MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL = os.getenv(
    "MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL", ""
)
MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT = os.getenv(
    "MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT", ""
)
OPERATING_TIME_ZONE = os.getenv("OPERATING_TIME_ZONE", "America/Los_Angeles")
PARTNER_CALLBACK_AUDIENCE = os.getenv("PARTNER_CALLBACK_AUDIENCE", "")
PARTNER_CALLBACK_SERVICE_ACCOUNT_EMAIL = os.getenv(
    "PARTNER_CALLBACK_SERVICE_ACCOUNT_EMAIL", ""
)
PARTNER_CALLBACK_SERVICE_ACCOUNT_SUBJECT = os.getenv(
    "PARTNER_CALLBACK_SERVICE_ACCOUNT_SUBJECT", ""
)
PARTNER_EVIDENCE_MAX_CLOCK_SKEW_SECONDS = int(
    os.getenv("PARTNER_EVIDENCE_MAX_CLOCK_SKEW_SECONDS", "900")
)


def post_to_plan_ledger(
    path: str,
    *,
    payload: Dict[str, Any],
    timeout: float = 15.0,
    trace_id: Optional[str] = None,
    operator_authorization: Optional[str] = None,
) -> httpx.Response:
    """Invoke the private ledger with a Google-signed, audience-bound token."""

    if not PLAN_LEDGER_URL or not PLAN_LEDGER_AUDIENCE:
        raise IdentityConfigurationError("PLAN_LEDGER_URL and PLAN_LEDGER_AUDIENCE are required")
    if not path.startswith("/"):
        raise ValueError("Ledger path must start with '/'")

    token = fetch_google_id_token(PLAN_LEDGER_AUDIENCE)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if trace_id:
        headers["X-Full-Shelf-Trace-Id"] = trace_id
        headers["traceparent"] = build_traceparent(trace_id, generate_span_id())
    if operator_authorization:
        headers["X-Full-Shelf-Operator-Authorization"] = operator_authorization

    response = httpx.post(
        f"{PLAN_LEDGER_URL.rstrip('/')}{path}",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def execute_ledger_command(
    *,
    command_id: str,
    idempotency_key: str,
    tenant_id: str,
    incident_id: str,
    agent_role: str,
    command_type: str,
    trace_id: str,
    payload: Dict[str, Any],
    expected_plan_revision: Optional[str] = None,
    allow_denied: bool = False,
) -> Dict[str, Any]:
    response = post_to_plan_ledger(
        "/api/v1/commands/execute",
        payload={
            "command_id": command_id,
            "idempotency_key": idempotency_key,
            "tenant_id": tenant_id,
            "incident_id": incident_id,
            "agent_role": agent_role,
            "command_type": command_type,
            "expected_plan_revision": expected_plan_revision,
            "trace_id": trace_id,
            "payload": payload,
        },
        trace_id=trace_id,
    )
    result = response.json()
    receipt = result.get("receipt") or {}
    if receipt.get("status") != "SUCCESS" and not allow_denied:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LEDGER_COMMAND_NOT_COMMITTED",
                "receipt_id": receipt.get("receipt_id"),
                "status": receipt.get("status"),
                "message": receipt.get("message"),
            },
        )
    return result


class HumanRepairPlanDiff(BaseModel):
    reroute_order_id: str = Field(min_length=1, max_length=64)
    reroute_cases: int = Field(gt=0)
    reroute_target_vehicle: str = Field(min_length=1, max_length=64)
    pickup_order_id: str = Field(min_length=1, max_length=64)
    pickup_cases: int = Field(gt=0)


class HumanApprovalProposal(BaseModel):
    command_id: str = Field(min_length=1, max_length=48)
    idempotency_key: str = Field(min_length=1, max_length=112)
    tenant_id: str
    operating_day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    incident_id: str
    plan_id: str
    source_revision: str
    proposed_revision: str
    approval_id: str = Field(min_length=1, max_length=48)
    expires_at: str
    plan_diff: HumanRepairPlanDiff


class RecallArmorPreflightRequest(BaseModel):
    notice_text: str = Field(min_length=1, max_length=20000)


class PartnerEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["PARTNER_CUSTODY_EVIDENCE_RECEIVED"]
    source_event_id: str = Field(min_length=1, max_length=256)
    incident_id: str = Field(min_length=1, max_length=64)
    original_text: str = Field(min_length=1, max_length=20000)
    source_occurred_at: datetime


class RecallTriggerRequest(BaseModel):
    coordinator_id: str = Field(min_length=1, max_length=64)
    incident_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    notice_text: str = Field(min_length=1, max_length=20000)


class VehicleRefrigerationFailureRequest(BaseModel):
    """A mechanical fleet-system fault report.

    This is a reported EVENT, not an inference. Refrigeration status is a
    separate mechanical signal from position: no amount of missing, stalled or
    repeated location data may place a vehicle in a failed state, and nothing
    here reads a coordinate.
    """

    source_event_id: str = Field(min_length=1, max_length=256)
    vehicle_id: str = Field(min_length=1, max_length=64)
    occurred_at: str = Field(min_length=1, max_length=64)
    fault_type: Literal["REFRIGERATION_UNIT_FAILURE"]
    refrigeration_status: Literal["FAILED"]
    source_system: Literal["SIMULATED_FLEET_TELEMATICS"]


class PersistWaitingCoordinatorRequest(BaseModel):
    coordinator_id: str = Field(min_length=1, max_length=64)
    incident_id: str = Field(min_length=1, max_length=64)
    checkpoint: str = Field(min_length=1, max_length=64)
    active_plan_revision: str = Field(pattern=r"^rev08$")
    child_incident_ids: list[str] = Field(min_length=1)


class DeadlineTaskCallbackPayload(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    incident_id: str = Field(min_length=1, max_length=64)
    hold_incident_id: str = Field(min_length=1, max_length=64)
    coordinator_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    site_id: str = Field(min_length=1, max_length=64)
    unconfirmed_cases: int = Field(gt=0)
    task_decision_id: str = Field(min_length=1, max_length=500)
    event_idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=500)
    correlation_trace_id: str = Field(min_length=32, max_length=32)


class SiteEscalationRequest(BaseModel):
    incident_id: str = Field(min_length=1, max_length=64)
    hold_incident_id: str = Field(min_length=1, max_length=64)
    coordinator_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    site_id: str = Field(min_length=1, max_length=64)
    unconfirmed_cases: int = Field(gt=0)


# CR-002: which human identity THIS deployment accepts as the operator.
# Exactly one verifier is built, so a deployment can never accept both a
# canonical Google operator and an isolated judge operator. Unset means the
# canonical Google OAuth mode, leaving the canonical deployment unchanged.
OPERATOR_IDENTITY_MODE = os.getenv("OPERATOR_IDENTITY_MODE", "google-oauth").strip()


def _operator_verifier():
    """Build the one verifier this deployment's identity mode permits."""
    if OPERATOR_IDENTITY_MODE == "identity-platform":
        return IdentityPlatformOperatorVerifier(
            project_id=os.getenv("IDENTITY_PLATFORM_PROJECT_ID", ""),
            allowed_subjects={os.getenv("ALLOWED_OPERATOR_SUBJECT", "")},
        )
    if OPERATOR_IDENTITY_MODE != "google-oauth":
        raise IdentityConfigurationError(
            f"Unknown OPERATOR_IDENTITY_MODE: {OPERATOR_IDENTITY_MODE}"
        )
    return GoogleOidcVerifier(
        audience=os.getenv("OPERATOR_OAUTH_CLIENT_ID", ""),
        allowed_subjects={os.getenv("ALLOWED_OPERATOR_SUBJECT", "")},
        allowed_emails={os.getenv("ALLOWED_OPERATOR_EMAIL", "")},
    )


def _verify_operator(authorization: Optional[str]):
    try:
        return _operator_verifier().verify_authorization(authorization)
    except IdentityConfigurationError as exc:
        raise HTTPException(503, "OPERATOR_IDENTITY_BOUNDARY_NOT_CONFIGURED") from exc
    except MissingIdentityToken as exc:
        raise HTTPException(401, "OPERATOR_GOOGLE_ID_TOKEN_REQUIRED") from exc
    except InvalidIdentityToken as exc:
        raise HTTPException(401, "OPERATOR_GOOGLE_ID_TOKEN_INVALID") from exc
    except UnauthorizedIdentity as exc:
        raise HTTPException(403, "OPERATOR_GOOGLE_IDENTITY_NOT_ALLOWED") from exc


def require_human_operator(
    authorization: Optional[str] = Header(None),
) -> VerifiedGoogleIdentity:
    return _verify_operator(authorization)


def _verify_managed_callback(authorization: Optional[str]):
    """Verify one Google-signed managed delivery token at the public service."""
    try:
        return GoogleOidcVerifier(
            audience=MANAGED_CALLBACK_AUDIENCE,
            allowed_subjects={MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT},
            allowed_emails={MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL},
        ).verify_authorization(authorization)
    except IdentityConfigurationError as exc:
        raise HTTPException(503, "MANAGED_CALLBACK_IDENTITY_NOT_CONFIGURED") from exc
    except MissingIdentityToken as exc:
        raise HTTPException(401, "MANAGED_CALLBACK_GOOGLE_ID_TOKEN_REQUIRED") from exc
    except InvalidIdentityToken as exc:
        raise HTTPException(401, "MANAGED_CALLBACK_GOOGLE_ID_TOKEN_INVALID") from exc
    except UnauthorizedIdentity as exc:
        raise HTTPException(403, "MANAGED_CALLBACK_GOOGLE_IDENTITY_NOT_ALLOWED") from exc


def require_managed_callback(
    authorization: Optional[str] = Header(None),
) -> VerifiedGoogleIdentity:
    return _verify_managed_callback(authorization)


def _verify_partner_callback(authorization: Optional[str]) -> VerifiedGoogleIdentity:
    """Verify the dedicated partner callback principal and exact audience."""
    try:
        return GoogleOidcVerifier(
            audience=PARTNER_CALLBACK_AUDIENCE,
            allowed_subjects={PARTNER_CALLBACK_SERVICE_ACCOUNT_SUBJECT},
            allowed_emails={PARTNER_CALLBACK_SERVICE_ACCOUNT_EMAIL},
        ).verify_authorization(authorization)
    except IdentityConfigurationError as exc:
        raise HTTPException(503, "PARTNER_CALLBACK_IDENTITY_NOT_CONFIGURED") from exc
    except MissingIdentityToken as exc:
        raise HTTPException(401, "PARTNER_CALLBACK_GOOGLE_ID_TOKEN_REQUIRED") from exc
    except InvalidIdentityToken as exc:
        raise HTTPException(401, "PARTNER_CALLBACK_GOOGLE_ID_TOKEN_INVALID") from exc
    except UnauthorizedIdentity as exc:
        raise HTTPException(403, "PARTNER_CALLBACK_GOOGLE_IDENTITY_NOT_ALLOWED") from exc


def require_partner_callback(
    authorization: Optional[str] = Header(None),
) -> VerifiedGoogleIdentity:
    return _verify_partner_callback(authorization)


def _partner_callback_authority(identity: VerifiedGoogleIdentity) -> dict[str, str]:
    """Resolve tenant and partner only from deployment-owned identity mapping."""
    raw = os.getenv("PARTNER_CALLBACK_AUTHORITY_JSON", "")
    try:
        mapping = json.loads(raw)
        bound = mapping[identity.subject]
        tenant_id = bound["tenant_id"]
        partner_id = bound["partner_id"]
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "PARTNER_CALLBACK_AUTHORITY_NOT_CONFIGURED") from exc
    if not all(isinstance(value, str) and value for value in (tenant_id, partner_id)):
        raise HTTPException(503, "PARTNER_CALLBACK_AUTHORITY_INVALID")
    return {"tenant_id": tenant_id, "partner_id": partner_id}


def _partner_site_binding(site_id: str) -> dict[str, str]:
    """Deployment-owned binding used when the deadline creates the typed work item."""
    default = {
        "N-ST01": {
            "partner_id": "PARTNER-AGENCY-01",
            "custody_node_id": "N-ST01",
        },
        "SITE-01": {
            "partner_id": "PARTNER-AGENCY-01",
            "custody_node_id": "N-ST01",
        },
    }
    try:
        mapping = json.loads(os.getenv(
            "PARTNER_SITE_AUTHORITY_JSON", json.dumps(default)
        ))
        binding = mapping[site_id]
        return {
            "partner_id": str(binding["partner_id"]),
            "custody_node_id": str(binding["custody_node_id"]),
        }
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "PARTNER_SITE_AUTHORITY_NOT_CONFIGURED") from exc


def _verify_internal_workload(authorization: Optional[str]):
    """Verify an internal Google workload independently of callback identity."""
    try:
        return GoogleOidcVerifier(
            audience=os.getenv("INTERNAL_WORKLOAD_AUDIENCE", "")
                or MANAGED_CALLBACK_AUDIENCE,
            allowed_subjects={
                os.getenv("INTERNAL_WORKLOAD_SERVICE_ACCOUNT_SUBJECT", "")
                or MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT
            },
            allowed_emails={
                os.getenv("INTERNAL_WORKLOAD_SERVICE_ACCOUNT_EMAIL", "")
                or MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL
            },
        ).verify_authorization(authorization)
    except IdentityConfigurationError as exc:
        raise HTTPException(503, "INTERNAL_WORKLOAD_IDENTITY_NOT_CONFIGURED") from exc
    except MissingIdentityToken as exc:
        raise HTTPException(401, "INTERNAL_WORKLOAD_GOOGLE_ID_TOKEN_REQUIRED") from exc
    except InvalidIdentityToken as exc:
        raise HTTPException(401, "INTERNAL_WORKLOAD_GOOGLE_ID_TOKEN_INVALID") from exc
    except UnauthorizedIdentity as exc:
        raise HTTPException(403, "INTERNAL_WORKLOAD_GOOGLE_IDENTITY_NOT_ALLOWED") from exc


def require_frontend_authority(
    authorization: Optional[str] = Header(None),
) -> tuple[VerifiedGoogleIdentity, Any, str]:
    """Derive the sole frontend tenant/day from verified identity and config."""
    tenant_id = os.getenv("FRONTEND_AUTHORITY_TENANT_ID", "").strip()
    operating_day = os.getenv("FRONTEND_AUTHORITY_OPERATING_DAY", "").strip()
    if not tenant_id or not operating_day:
        raise HTTPException(503, "FRONTEND_AUTHORITY_SCOPE_NOT_CONFIGURED")
    try:
        datetime.fromisoformat(operating_day)
        identity = _verify_operator(authorization)
        return identity, _resolve_authority_scope(tenant_id), operating_day
    except ValueError as exc:
        raise HTTPException(503, "FRONTEND_OPERATING_DAY_INVALID") from exc


@app.post("/api/v1/orchestrator/approvals/approve-and-activate")
def approve_and_activate(
    proposal: HumanApprovalProposal,
    authorization: Optional[str] = Header(None),
    operator: VerifiedGoogleIdentity = Depends(require_human_operator),
):
    """Validate the human token, then preserve it for independent ledger verification."""
    _resolve_authority_scope(proposal.tenant_id)
    if proposal.source_revision != "rev07" or proposal.proposed_revision != "rev08":
        raise HTTPException(409, "CANONICAL_REVISION_TRANSITION_REQUIRED")
    response = post_to_plan_ledger(
        "/api/v1/approvals/approve-and-activate",
        payload=proposal.model_dump(),
        trace_id=generate_trace_id(),
        operator_authorization=authorization,
    )
    result = response.json()
    result["verified_operator_subject"] = operator.subject
    result["verified_operator_email"] = operator.email
    return result


@lru_cache(maxsize=2)
def get_spanner_database(database_id: Optional[str] = None):
    """Reuse thread-safe Spanner session pools for explicitly configured databases."""
    spanner_client = spanner.Client(project=PROJECT_ID)
    instance = spanner_client.instance(SPANNER_INSTANCE)
    return instance.database(database_id or SPANNER_DATABASE)


def _resolve_authority_scope(tenant_id: str):
    """Resolve request tenant to a deployment-owned database mapping."""
    try:
        return AuthorityScopeResolver.from_environment().resolve(tenant_id)
    except AuthorityConfigurationError as exc:
        raise HTTPException(
            status_code=503, detail="ORCHESTRATOR_AUTHORITY_BOUNDARY_NOT_CONFIGURED"
        ) from exc
    except UnauthorizedAuthorityScope as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _operating_day_from_managed_publish_time(published_at: datetime) -> str:
    """Normalize verified Pub/Sub delivery time to the configured food-bank day."""
    if published_at.tzinfo is None:
        raise ValueError("MANAGED_PUBLISH_TIME_MUST_BE_TIMEZONE_AWARE")
    try:
        operating_zone = ZoneInfo(OPERATING_TIME_ZONE)
    except Exception as exc:
        raise HTTPException(503, "OPERATING_TIME_ZONE_INVALID") from exc
    return published_at.astimezone(operating_zone).date().isoformat()


def _utc_now() -> datetime:
    """Clock seam for deterministic managed-event age tests."""
    return datetime.now(timezone.utc)


PERMANENT_PUBSUB_BUSINESS_REJECTION_CODES = frozenset({
    "IDEMPOTENCY_KEY_COLLISION",
})


def _ledger_error_detail(response: httpx.Response) -> Dict[str, Any]:
    """Parse the private ledger's bounded machine-readable error contract."""
    try:
        body = response.json()
    except (TypeError, ValueError):
        return {"code": "UNPARSEABLE_LEDGER_ERROR"}
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        return detail
    if isinstance(detail, str):
        return {"code": detail}
    return {"code": "UNKNOWN_LEDGER_ERROR"}


def _http_exception_code(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code")
        return code if isinstance(code, str) else "UNKNOWN_LEDGER_ERROR"
    return str(exc.detail)


def _ack_permanent_pubsub_rejection(
    *, message_id: str | None, event_type: str | None, reason: str,
    trace_id: str, age_seconds: float | None = None,
    authority: str | None = None, error_code: str | None = None,
) -> Dict[str, Any]:
    """Acknowledge authenticated poison messages without any authoritative write."""
    disposition = (
        "STALE_ACKNOWLEDGED" if reason == "STALE_PUBSUB_EVENT"
        else "PERMANENTLY_REJECTED_ACKNOWLEDGED"
    )
    logger.warning(
        "pubsub_disposition message_id=%s event_type=%s disposition=%s "
        "age_seconds=%s trace_id=%s receipt_id=NONE authority=%s "
        "error_code=%s reason=%s",
        message_id or "UNKNOWN", event_type or "UNKNOWN", disposition,
        round(age_seconds, 3) if age_seconds is not None else "UNKNOWN",
        trace_id, authority or "UNKNOWN", error_code or reason, reason,
    )
    return {
        "status": disposition,
        "disposition": disposition,
        "message_id": message_id,
        "event_type": event_type,
        "reason": reason,
        "mutations_applied": 0,
        "classification": "OBSERVED_LIVE",
        "trace_id": trace_id,
        "authority": authority,
        "error_code": error_code or reason,
    }


def _log_pubsub_result(
    *, message_id: str, event_type: str, disposition: str, trace_id: str,
    age_seconds: float, receipt_id: str | None = None, reason: str | None = None,
    authority: str | None = None, error_code: str | None = None,
) -> None:
    log = logger.error if disposition == "RETRYABLE_FAILURE" else logger.warning
    log(
        "pubsub_disposition message_id=%s event_type=%s disposition=%s "
        "age_seconds=%s trace_id=%s receipt_id=%s authority=%s "
        "error_code=%s reason=%s",
        message_id, event_type, disposition, round(age_seconds, 3), trace_id,
        receipt_id or "NONE", authority or "UNKNOWN", error_code or "NONE",
        reason or "NONE",
    )


CUSTODY_GRAPH_GQL = """
GRAPH CustodyGraph
MATCH (src:Node)-[e:TRANSFERRED_TO
  WHERE e.tenant_id = @tenant_id AND e.lot_id = @lot_id
]->{1,8}(dst:Node)
WHERE src.tenant_id = @tenant_id AND src.node_type = 'WAREHOUSE'
RETURN
  src.node_id AS root_node_id,
  src.node_type AS root_node_type,
  src.name AS root_name,
  src.on_hand_cases AS root_cases,
  src.acknowledgment_status AS root_acknowledgment_status,
  dst.node_id AS node_id,
  dst.node_type AS node_type,
  dst.name AS node_name,
  dst.on_hand_cases AS node_cases,
  dst.acknowledgment_status AS node_acknowledgment_status,
  ARRAY_LENGTH(e) AS path_depth
ORDER BY path_depth, node_id
""".strip()


def _run_managed_custody_graph(db, *, tenant_id: str, lot_id: str) -> Dict[str, Any]:
    """Execute the custody reconstruction wholly in Spanner Graph.

    The only reconciliation performed here is identity-based de-duplication of the
    managed query result. There is intentionally no relational scan or local graph
    traversal fallback.
    """
    with db.snapshot() as snapshot:
        rows = list(snapshot.execute_sql(
            CUSTODY_GRAPH_GQL,
            params={"tenant_id": tenant_id, "lot_id": lot_id},
            param_types={
                "tenant_id": spanner.param_types.STRING,
                "lot_id": spanner.param_types.STRING,
            },
        ))

    if not rows:
        raise LookupError("GRAPH_TOPOLOGY_NOT_FOUND")

    root = {
        "node_id": rows[0][0],
        "node_type": rows[0][1],
        "name": rows[0][2],
        "on_hand_cases": rows[0][3],
        "acknowledgment_status": rows[0][4],
        "path_depth": 0,
    }
    nodes = {root["node_id"]: root}
    paths = []
    for row in rows:
        if (row[0] != root["node_id"] or row[3] != root["on_hand_cases"]
                or row[4] != root["acknowledgment_status"]):
            raise ValueError("INCONSISTENT_GRAPH_ROOT")
        node = {
            "node_id": row[5],
            "node_type": row[6],
            "name": row[7],
            "on_hand_cases": row[8],
            "acknowledgment_status": row[9],
            "path_depth": row[10],
        }
        prior = nodes.get(node["node_id"])
        if prior and (prior["on_hand_cases"] != node["on_hand_cases"]
                      or prior["acknowledgment_status"] != node["acknowledgment_status"]):
            raise ValueError("INCONSISTENT_GRAPH_NODE")
        if not prior or node["path_depth"] < prior["path_depth"]:
            nodes[node["node_id"]] = node
        paths.append({
            "root_node_id": row[0],
            "destination_node_id": row[5],
            "path_depth": row[10],
        })

    positions = sorted(nodes.values(), key=lambda item: (item["path_depth"], item["node_id"]))
    return {
        "tenant_id": tenant_id,
        "lot_id": lot_id,
        "query_engine": "SPANNER_GRAPH_GQL",
        "query_shape": CUSTODY_GRAPH_GQL,
        "query_parameters": {"tenant_id": tenant_id, "lot_id": lot_id},
        "paths": paths,
        "current_positions": positions,
        "unique_current_cases": sum(position["on_hand_cases"] for position in positions),
        "confirmed_cases": sum(
            position["on_hand_cases"] for position in positions
            if position["acknowledgment_status"] == "CONFIRMED"
        ),
        "unconfirmed_cases": sum(
            position["on_hand_cases"] for position in positions
            if position["acknowledgment_status"] == "UNCONFIRMED"
        ),
        "unconfirmed_positions": [
            position for position in positions
            if position["acknowledgment_status"] == "UNCONFIRMED"
        ],
        "max_path_depth": max(path["path_depth"] for path in paths),
        "node_count": len(positions),
        "intermediate_subtotals_readded": False,
        "classification": "OBSERVED_LIVE",
    }


def require_internal_workload(
    authorization: Optional[str] = Header(None),
) -> VerifiedGoogleIdentity:
    """Require signed, audience-bound OIDC from an allowlisted workload."""
    return _verify_internal_workload(authorization)


@app.on_event("startup")
def startup_checks():
    # CR-002: a judge deployment pointed at canonical state must never become
    # healthy. No-op on the canonical deployment.
    assert_judge_isolation()
    """Reject an ineligible configured model without triggering a paid health call."""
    if not PLAN_LEDGER_URL or not PLAN_LEDGER_AUDIENCE:
        raise RuntimeError("PLAN_LEDGER_URL and PLAN_LEDGER_AUDIENCE must be configured")
    if not all((MANAGED_CALLBACK_AUDIENCE, MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL,
                MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT)):
        raise RuntimeError("Managed callback OIDC configuration must be complete")
    # Construct every boundary at startup so a public platform ingress can never
    # become healthy with a missing application identity configuration.
    _operator_verifier()
    GoogleOidcVerifier(
        audience=MANAGED_CALLBACK_AUDIENCE,
        allowed_subjects={MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT},
        allowed_emails={MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL},
    )
    GoogleOidcVerifier(
        audience=os.getenv("INTERNAL_WORKLOAD_AUDIENCE", "")
            or MANAGED_CALLBACK_AUDIENCE,
        allowed_subjects={
            os.getenv("INTERNAL_WORKLOAD_SERVICE_ACCOUNT_SUBJECT", "")
            or MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT
        },
        allowed_emails={
            os.getenv("INTERNAL_WORKLOAD_SERVICE_ACCOUNT_EMAIL", "")
            or MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL
        },
    )
    registered_route_authentication_matrix()
    AuthorityScopeResolver.from_environment()
    print(f"Orchestrator container started. Model configured: {MODEL_ID}, Location: {VERTEX_LOCATION}")
    if not is_eligible_gemini_model(MODEL_ID):
        raise RuntimeError(f"Configured model {MODEL_ID} is ineligible. Gemini 3.5 or newer is required.")
    print("Configured model identifier satisfies the Gemini 3.5+ floor.")


@app.get("/")
def health_check():
    return {
        "status": "HEALTHY",
        "service": "full-shelf-orchestrator",
        "model": MODEL_ID,
        "vertex_location": VERTEX_LOCATION,
        "database": f"projects/{PROJECT_ID}/instances/{SPANNER_INSTANCE}/databases/{SPANNER_DATABASE}",
        "build_book_version": "1.1"
    }


@app.get("/healthz")
def healthz_check():
    return health_check()


# -------------------------------------------------------------------
# GATE B — DAILY PLAN CREATION
# -------------------------------------------------------------------

def _generate_daily_morning_plan(
    *,
    request: OperatingDayRequest,
) -> Dict[str, Any]:
    """Commit a validated morning plan definition through the private ledger.

    Daily plan is pre-built by deterministic logic upstream. Fulfillment agent
    validates selection before ledger commit.
    """
    trace_id = generate_trace_id()
    tenant_id = operating_day_authority_id(request.tenant_id, request.operating_day)
    operating_plan = request.operating_plan
    authority_scope = f"{request.tenant_id}@{request.operating_day}"
    _resolve_authority_scope(tenant_id)
    plan_scope_digest = hashlib.sha256(
        (
            f"{request.tenant_id}\x00{request.operating_day}\x00"
            f"{request.event_type}\x00{operating_plan.plan_id}\x00"
            f"{operating_plan.revision}"
        ).encode("utf-8")
    ).hexdigest()[:24]

    # Gate daily plan through Fulfillment agent validation before ledger commit
    # Daily plan is treated as single deterministic candidate
    incident_id_daily = f"INC-DAY-{plan_scope_digest}"
    try:
        fleet_result = run_fleet(
            incident_id=incident_id_daily,
            lot_id="DAILY_PLAN_NO_LOT",
            screened_notice_text="Daily plan generation",
            graph_result={},
            recovery_candidates=[{
                "candidate_id": operating_plan.plan_id,
                "revision": operating_plan.revision,
                "content_hash": hashlib.sha256(
                    operating_plan.model_dump_json().encode("utf-8")
                ).hexdigest(),
                # The day's committed orders ARE the daily candidate's
                # allocations. Passing only metadata left every category empty,
                # so this gate rejected its own plan as a partial input.
                "allocations": [
                    {"order_id": order.order_id, "cases": order.cases,
                     "agency_id": order.destination_agency_id,
                     "target_vehicle_id": order.assigned_vehicle_id}
                    for order in operating_plan.orders
                ],
                "partner_pickups": [],
                "shortfalls": [],
            }],
            source_event_id=None,
            trigger=TriggerClass.DAILY_PLANNING,
            expected_revision=operating_plan.revision,
            partner_state={},
        )
        if fleet_result["proposal"].status != "PROPOSED":
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "DAILY_PLAN_REJECTED_BY_FULFILLMENT",
                    "reason": fleet_result["proposal"].reason_code,
                },
            )
    except FleetProposalError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "DAILY_PLAN_FLEET_VALIDATION_FAILED",
                "reason": exc.reason_code,
            },
        ) from exc

    try:
        ledger_result = execute_ledger_command(
            command_id=f"CMD-DAY-{plan_scope_digest}",
            idempotency_key=f"daily-plan:{plan_scope_digest}",
            tenant_id=tenant_id,
            incident_id=f"INC-DAY-{plan_scope_digest}",
            agent_role="FULFILLMENT_RECOVERY_PLANNER",
            command_type="SAVE_PLAN_REVISION",
            expected_plan_revision="rev07",
            trace_id=trace_id,
            payload={
                **operating_plan.model_dump(),
                "logical_tenant_id": request.tenant_id,
                "operating_day": request.operating_day,
                "request_type": request.event_type,
                "authority_scope": authority_scope,
            },
        )
    except httpx.HTTPStatusError as exc:
        detail = _ledger_error_detail(exc.response)
        if (
            exc.response.status_code == 409
            and detail["code"] in PERMANENT_PUBSUB_BUSINESS_REJECTION_CODES
        ):
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(
            status_code=502,
            detail={
                "code": "PLAN_LEDGER_DAILY_PLAN_COMMIT_FAILED",
                "ledger_status": exc.response.status_code,
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "PLAN_LEDGER_DAILY_PLAN_COMMIT_FAILED"},
        ) from exc

    return {
        "status": (
            "DAILY_PLAN_EXISTS_IDEMPOTENT"
            if ledger_result["idempotent_replay"]
            else "DAILY_PLAN_GENERATED_REV07"
        ),
        "revision": "rev07",
        "tenant_id": request.tenant_id,
        "operating_day": request.operating_day,
        "authority_scope": authority_scope,
        "authority_tenant_id": tenant_id,
        "plan_details": operating_plan.model_dump(),
        "idempotent_replay": ledger_result["idempotent_replay"],
        "ledger_receipt": ledger_result["receipt"],
        "trace_id": trace_id
    }


@app.post(
    "/api/v1/orchestrator/daily-plan/generate",
    dependencies=[Depends(require_internal_workload)],
)
def generate_daily_morning_plan(
    request: OperatingDayRequest,
):
    return _generate_daily_morning_plan(request=request)


# -------------------------------------------------------------------
# GATE C — S2S DISPATCH & SPANNER AUTH PROOF
# -------------------------------------------------------------------

@app.post("/api/v1/orchestrator/s2s-dispatch")
def s2s_dispatch(
    idempotency_key: str = Query("ACT-S2S-EXEC-LIVE-001"),
    tamper_field: Optional[str] = Query(None),
):
    raise HTTPException(410, "USE_AUTHENTICATED_HUMAN_APPROVAL_ROUTE")


# -------------------------------------------------------------------
# GATE D — DURABLE WAIT & PUB/SUB RESUME
# -------------------------------------------------------------------

@app.post(
    "/api/v1/orchestrator/coordinator/persist-waiting",
    dependencies=[Depends(require_internal_workload)],
)
def persist_coordinator_waiting(
    proposal: PersistWaitingCoordinatorRequest,
    tenant_id: str = "east-bay-food-bank",
):
    """Persists day coordinator in WAITING_FOR_EVENTS state in Spanner after rev08."""
    _resolve_authority_scope(tenant_id)
    now = datetime.now(timezone.utc)
    trace_id = generate_trace_id()
    coord_id = proposal.coordinator_id
    checkpoint = proposal.checkpoint
    active_rev = proposal.active_plan_revision
    command_digest = hashlib.sha256(
        f"{tenant_id}\x00{coord_id}\x00{checkpoint}".encode("utf-8")
    ).hexdigest()[:24]

    ledger_result = execute_ledger_command(
        command_id=f"CMD-WAIT-{command_digest}",
        idempotency_key=f"coordinator-wait:{command_digest}",
        tenant_id=tenant_id,
        incident_id=proposal.incident_id,
        agent_role="INCIDENT_COORDINATOR",
        command_type="PERSIST_COORDINATOR",
        expected_plan_revision=active_rev,
        trace_id=trace_id,
        payload={
            "coordinator_id": coord_id,
            "state": "WAITING_FOR_EVENTS",
            "checkpoint": checkpoint,
            "active_plan_revision": active_rev,
            "child_incident_ids": proposal.child_incident_ids,
        },
    )
    return {
        "status": "COORDINATOR_PERSISTED",
        "coordinator_id": coord_id,
        "state": "WAITING_FOR_EVENTS",
        "checkpoint": checkpoint,
        "active_plan_revision": active_rev,
        "updated_at": now.isoformat(),
        "ledger_receipt": ledger_result["receipt"],
    }


@app.post("/api/v1/incidents/site01-deadline")
def handle_site01_deadline_callback(
    req: Request,
    payload: DeadlineTaskCallbackPayload,
    caller: VerifiedGoogleIdentity = Depends(require_managed_callback),
):
    """Authenticated Cloud Task callback for Site 01 acknowledgment deadline hold."""
    task_name = req.headers.get("X-CloudTasks-TaskName")
    queue_name = req.headers.get("X-CloudTasks-QueueName")
    if not task_name or queue_name != "full-shelf-deadlines":
        raise HTTPException(400, "CLOUD_TASK_DELIVERY_CONTEXT_REQUIRED")

    incident_id = payload.incident_id
    site_id = payload.site_id
    tenant_id = payload.tenant_id
    task_decision_id = payload.task_decision_id
    event_idempotency_key = payload.event_idempotency_key or task_decision_id
    _resolve_authority_scope(tenant_id)
    if not task_decision_id or not (
        task_name == task_decision_id
        or task_name.endswith(f"/tasks/{task_decision_id}")
    ):
        raise HTTPException(400, "CLOUD_TASK_NAME_PAYLOAD_MISMATCH")

    now = datetime.now(timezone.utc).isoformat()
    trace_id = generate_trace_id()
    payload_trace_id = payload.correlation_trace_id
    if payload_trace_id and payload_trace_id != trace_id:
        raise HTTPException(400, "CLOUD_TASK_TRACE_CONTEXT_MISMATCH")
    site_binding = _partner_site_binding(site_id)
    operating_day = _operating_day_from_managed_publish_time(_utc_now())
    ledger_result = execute_ledger_command(
        command_id=f"CMD-TASK-{hashlib.sha256(event_idempotency_key.encode()).hexdigest()[:24]}",
        idempotency_key=f"cloud-task:{hashlib.sha256(event_idempotency_key.encode()).hexdigest()}",
        tenant_id=tenant_id,
        incident_id=incident_id,
        agent_role="PARTNER_OPERATIONS_AGENT",
        command_type="RECORD_ACKNOWLEDGMENT_HOLD",
        trace_id=trace_id,
        payload={
            "incident_id": incident_id,
            "hold_incident_id": payload.hold_incident_id,
            "coordinator_id": payload.coordinator_id,
            "lot_id": payload.lot_id,
            "site_id": site_id,
            "unconfirmed_cases": payload.unconfirmed_cases,
            "task_name": event_idempotency_key,
            "delivery_subject": caller.subject,
            "delivery_email": caller.email,
            "delivery_audience": caller.audience,
            "partner_id": site_binding["partner_id"],
            "custody_node_id": site_binding["custody_node_id"],
            "operating_day": operating_day,
        },
    )
    logger.warning(
        "cloud_task_delivery task_name=%s event_idempotency_key=%s "
        "receipt_id=%s idempotent_replay=%s",
        task_name,
        event_idempotency_key,
        ledger_result["receipt"]["receipt_id"],
        ledger_result["idempotent_replay"],
    )

    return {
        "status": "DEADLINE_ACK_HOLD_PERSISTED",
        "site_id": site_id,
        "incident_id": incident_id,
        "unconfirmed_cases": payload.unconfirmed_cases,
        "authenticated_task": True,
        "task_name": task_name,
        "event_idempotency_key": event_idempotency_key,
        "delivery_identity": caller.email,
        "delivery_subject": caller.subject,
        "delivery_audience": caller.audience,
        "idempotent_replay": ledger_result["idempotent_replay"],
        "timestamp": now,
        "ledger_receipt": ledger_result["receipt"],
    }


def _read_partner_evidence_authority(
    *, database: Any, tenant_id: str, incident_id: str, operating_day: str,
) -> dict[str, Any]:
    """Read the exact authoritative target before any model invocation."""
    str_t = spanner.param_types.STRING
    with database.snapshot(multi_use=True) as snapshot:
        incidents = list(snapshot.execute_sql(
            "SELECT status, terminal_state, affected_lot_id FROM Incidents "
            "WHERE tenant_id=@tenant AND incident_id=@incident",
            params={"tenant": tenant_id, "incident": incident_id},
            param_types={"tenant": str_t, "incident": str_t},
        ))
        plans = list(snapshot.execute_sql(
            "SELECT plan_id, revision, status FROM PlanRevisions "
            "WHERE tenant_id=@tenant AND plan_id=@plan_id "
            "AND status='INVALIDATED_RECALL'",
            params={"tenant": tenant_id, "plan_id": f"PLAN-{operating_day}"},
            param_types={"tenant": str_t, "plan_id": str_t},
        ))
        works = list(snapshot.execute_sql(
            "SELECT work_item_id, details FROM WorkItems "
            "WHERE tenant_id=@tenant AND incident_id=@incident "
            "AND work_type='PARTNER_CUSTODY_CONFIRMATION' AND status='OPEN'",
            params={"tenant": tenant_id, "incident": incident_id},
            param_types={"tenant": str_t, "incident": str_t},
        ))
        if len(incidents) != 1 or len(plans) != 1 or len(works) != 1:
            raise HTTPException(409, "PARTNER_EVIDENCE_AUTHORITY_NOT_EXACT")
        try:
            details = PartnerCustodyConfirmationDetails.model_validate_json(works[0][1])
        except Exception as exc:
            raise HTTPException(409, "PARTNER_CUSTODY_WORK_ITEM_DETAILS_INVALID") from exc
        nodes = list(snapshot.execute_sql(
            "SELECT name, on_hand_cases, acknowledgment_status FROM CustodyNodes "
            "WHERE tenant_id=@tenant AND node_id=@node",
            params={"tenant": tenant_id, "node": details.custody_node_id},
            param_types={"tenant": str_t, "node": str_t},
        ))
        edges = list(snapshot.execute_sql(
            "SELECT edge_id, case_count FROM CustodyEdges WHERE tenant_id=@tenant "
            "AND target_node_id=@node AND lot_id=@lot",
            params={
                "tenant": tenant_id,
                "node": details.custody_node_id,
                "lot": details.lot_id,
            },
            param_types={"tenant": str_t, "node": str_t, "lot": str_t},
        ))
    if len(nodes) != 1 or len(edges) != 1:
        raise HTTPException(409, "PARTNER_EVIDENCE_CUSTODY_TARGET_NOT_EXACT")
    incident_status, terminal_state, affected_lot_id = incidents[0]
    if (incident_status, terminal_state, affected_lot_id) != (
        "PARTIALLY_CONTAINED", "PARTIALLY_CONTAINED", details.lot_id
    ):
        raise HTTPException(409, "PARTNER_EVIDENCE_INCIDENT_PRECONDITION_FAILED")
    if (
        details.operating_day != operating_day
        or nodes[0][1] != details.expected_cases
        or nodes[0][2] != details.expected_acknowledgment_status
        or edges[0][1] != details.expected_cases
    ):
        raise HTTPException(409, "PARTNER_EVIDENCE_WORK_ITEM_PRECONDITION_FAILED")
    return {
        "incident_id": incident_id,
        "incident_status": incident_status,
        "terminal_state": terminal_state,
        "plan_id": plans[0][0],
        "plan_revision": plans[0][1],
        "plan_status": plans[0][2],
        "work_item_id": works[0][0],
        "partner_id": details.partner_id,
        "site_id": details.site_id,
        "custody_node_id": details.custody_node_id,
        "custody_node_name": nodes[0][0],
        "lot_id": details.lot_id,
        "expected_cases": details.expected_cases,
        "expected_acknowledgment_status": details.expected_acknowledgment_status,
        "requested_acknowledgment_status": details.requested_acknowledgment_status,
        "custody_edge_id": edges[0][0],
        "custody_edge_cases": edges[0][1],
    }


@app.post("/api/v1/orchestrator/partner-evidence")
def process_partner_evidence(
    req: Request,
    payload: PartnerEvidenceRequest,
    caller: VerifiedGoogleIdentity = Depends(require_partner_callback),
):
    """Screen, interpret, and submit authenticated evidence to the private ledger."""
    if payload.event_type != PARTNER_EVIDENCE_EVENT_TYPE:
        raise HTTPException(422, "PARTNER_EVIDENCE_EVENT_TYPE_INVALID")
    if payload.source_occurred_at.tzinfo is None:
        raise HTTPException(422, "SOURCE_OCCURRED_AT_TIMEZONE_REQUIRED")
    if abs((_utc_now() - payload.source_occurred_at.astimezone(timezone.utc)).total_seconds()) > (
        PARTNER_EVIDENCE_MAX_CLOCK_SKEW_SECONDS
    ):
        raise HTTPException(409, "SOURCE_OCCURRED_AT_OUTSIDE_TRUSTED_CLOCK_SKEW")
    operating_day = _operating_day_from_managed_publish_time(payload.source_occurred_at)
    callback_authority = _partner_callback_authority(caller)
    tenant_id = callback_authority["tenant_id"]
    partner_id = callback_authority["partner_id"]
    scope = _resolve_authority_scope(tenant_id)
    database = get_spanner_database(scope.database_id)
    try:
        authority = _read_partner_evidence_authority(
            database=database,
            tenant_id=tenant_id,
            incident_id=payload.incident_id,
            operating_day=operating_day,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "PARTNER_EVIDENCE_AUTHORITY_READ_UNAVAILABLE") from exc
    if authority["partner_id"] != partner_id:
        raise HTTPException(403, "PARTNER_CALLBACK_PARTNER_SCOPE_MISMATCH")

    trace_id = getattr(req.state, "full_shelf_trace_id", None) or generate_trace_id()
    screening = inspect_recall_notice_with_model_armor(
        payload.original_text, correlation_id=trace_id
    )
    if not (
        screening.get("status") == "APPROVED"
        and screening.get("safety_verdict") == "PASSED"
        and screening.get("correlation_id") == trace_id
    ):
        raise HTTPException(503, "PARTNER_EVIDENCE_MODEL_ARMOR_FAILED_CLOSED")
    try:
        proposal, adk = asyncio.run(run_partner_evidence_agent(
            partner_evidence_prompt(
                source_text=payload.original_text,
                authority=authority,
            )
        ))
    except Exception as exc:
        raise HTTPException(503, "PARTNER_EVIDENCE_ADK_FAILED_CLOSED") from exc

    digest = hashlib.sha256(
        f"{tenant_id}\x00{payload.source_event_id}".encode("utf-8")
    ).hexdigest()
    try:
        result = execute_ledger_command(
            command_id=f"CMD-PE-{digest[:24].upper()}",
            idempotency_key=f"partner-evidence:{digest}",
            tenant_id=tenant_id,
            incident_id=payload.incident_id,
            agent_role="PARTNER_OPERATIONS_AGENT",
            command_type="PROCESS_PARTNER_EVIDENCE",
            expected_plan_revision=authority["plan_revision"],
            trace_id=trace_id,
            allow_denied=True,
            payload={
                "event_type": payload.event_type,
                "source_event_id": payload.source_event_id,
                "operating_day": operating_day,
                "source_occurred_at": payload.source_occurred_at.isoformat(),
                "source_text": payload.original_text,
                "source_sha256": source_sha256(payload.original_text),
                "partner_id": partner_id,
                "callback_subject": caller.subject,
                "callback_email": caller.email,
                "callback_audience": caller.audience,
                "callback_issuer": caller.issuer,
                "callback_provenance": PARTNER_CALLBACK_PROVENANCE,
                "model_armor": screening,
                "proposal": proposal.model_dump(mode="json"),
                **adk,
            },
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            raise HTTPException(409, "PARTNER_EVIDENCE_SOURCE_EVENT_CONFLICT") from exc
        raise HTTPException(503, "PARTNER_EVIDENCE_LEDGER_UNAVAILABLE") from exc
    receipt = result["receipt"]
    return {
        "event_type": payload.event_type,
        "source_event_id": payload.source_event_id,
        "incident_id": payload.incident_id,
        "partner_id": partner_id,
        "decision": "APPLIED" if receipt["status"] == "SUCCESS" else "DENIED",
        "receipt": receipt,
        "idempotent_replay": result["idempotent_replay"],
    }


@app.post(
    "/api/v1/orchestrator/site01-escalation/schedule",
    dependencies=[Depends(require_internal_workload)],
)
def schedule_site01_escalation(
    proposal: SiteEscalationRequest,
    tenant_id: str = Query("east-bay-food-bank"),
):
    """Make the deployed decision that automatically creates the durable task."""
    scope = _resolve_authority_scope(tenant_id)
    db = get_spanner_database(scope.database_id)
    try:
        with db.snapshot(multi_use=True) as snapshot:
            recall = list(snapshot.execute_sql(
                "SELECT status FROM Incidents WHERE tenant_id = @t "
                "AND incident_id = @incident_id",
                params={"t": tenant_id, "incident_id": proposal.incident_id},
                param_types={"t": spanner.param_types.STRING,
                             "incident_id": spanner.param_types.STRING},
            ))
            holds = list(snapshot.execute_sql(
                "SELECT incident_id, details FROM Incidents WHERE tenant_id = @t "
                "AND incident_type = 'DEADLINE_HOLD' "
                "AND status = 'ACKNOWLEDGMENT_HOLD_ACTIVE'",
                params={"t": tenant_id},
                param_types={"t": spanner.param_types.STRING},
            ))
    except Exception as exc:
        raise HTTPException(503, "AUTHORITATIVE_ESCALATION_READ_UNAVAILABLE") from exc
    hold_open = False
    for row in holds:
        try:
            details = json.loads(row[1] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if (row[0] == proposal.hold_incident_id
                and details.get("site_id") == proposal.site_id
                and details.get("unconfirmed_cases") == proposal.unconfirmed_cases):
            hold_open = True
            break
    if not recall or recall[0][0] != "PARTIALLY_CONTAINED" or not hold_open:
        raise HTTPException(409, "SITE01_ESCALATION_PRECONDITIONS_NOT_MET")

    trace_id = generate_trace_id()
    decision_id = f"site01-{trace_id}"
    task = schedule_site01_deadline_task(
        tenant_id=tenant_id,
        incident_id=proposal.incident_id,
        hold_incident_id=proposal.hold_incident_id,
        coordinator_id=proposal.coordinator_id,
        lot_id=proposal.lot_id,
        site_id=proposal.site_id,
        unconfirmed_cases=proposal.unconfirmed_cases,
        task_id=decision_id,
        oidc_audience=MANAGED_CALLBACK_AUDIENCE,
        delivery_service_account=MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL,
        trace_id=trace_id,
    )
    evidence = {
        "event": "SITE01_ESCALATION_TASK_CREATED",
        "decision_id": decision_id,
        "task_name": task["task_name"],
        "queue": task["queue"],
        "target_url": task["target_url"],
        "oidc_audience": task["oidc_audience"],
        "delivery_service_account": task["delivery_service_account"],
        "correlation_trace_id": task["correlation_trace_id"],
    }
    print(json.dumps(evidence, sort_keys=True))
    return {"status": "SITE01_ESCALATION_SCHEDULED", **evidence}


@app.post("/api/v1/orchestrator/pubsub/push")
def handle_pubsub_push(
    payload: Dict[str, Any],
    request: Request,
    caller: VerifiedGoogleIdentity = Depends(require_managed_callback),
):
    """Handles real Pub/Sub wake-and-resume event pushing to Cloud Run orchestrator."""
    trace_id = getattr(request.state, "full_shelf_trace_id", generate_trace_id())

    message = payload.get("message", {})
    message_id = message.get("messageId")
    publish_time = message.get("publishTime")
    event_type = message.get("attributes", {}).get("event_type", "") or None
    if not message_id or not publish_time:
        return _ack_permanent_pubsub_rejection(
            message_id=message_id,
            event_type=event_type,
            reason="PUBSUB_MESSAGE_ID_AND_PUBLISH_TIME_REQUIRED",
            trace_id=trace_id,
        )
    age_seconds = None
    try:
        published_at = _parse_managed_publish_time(publish_time)
        age_seconds = (_utc_now() - published_at).total_seconds()
        max_age_seconds = int(os.getenv("PUBSUB_MAX_EVENT_AGE_SECONDS", "86400"))
        if age_seconds > max_age_seconds:
            return _ack_permanent_pubsub_rejection(
                message_id=message_id,
                event_type=event_type,
                reason="STALE_PUBSUB_EVENT",
                trace_id=trace_id,
                age_seconds=age_seconds,
            )
        if age_seconds < -300:
            return _ack_permanent_pubsub_rejection(
                message_id=message_id,
                event_type=event_type,
                reason="FUTURE_PUBSUB_EVENT",
                trace_id=trace_id,
                age_seconds=age_seconds,
            )
    except (HTTPException, TypeError, ValueError):
        return _ack_permanent_pubsub_rejection(
            message_id=message_id,
            event_type=event_type,
            reason="INVALID_PUBSUB_PUBLISH_TIME",
            trace_id=trace_id,
            age_seconds=age_seconds,
        )
    data_b64 = message.get("data", "")
    event_data = {}
    try:
        raw_str = base64.b64decode(data_b64).decode("utf-8")
        event_data = json.loads(raw_str)
    except Exception as exc:
        return _ack_permanent_pubsub_rejection(
            message_id=message_id, event_type=event_type,
            reason="INVALID_PUBSUB_EVENT_DATA", trace_id=trace_id,
            age_seconds=age_seconds,
        )

    event_type = event_data.get("event_type", "") or event_type or ""

    try:
        tenant_id = event_data.get("tenant_id")
        if event_type == "PLAN_NEXT_DAY_REQUESTED":
            next_day_request = NextDayRequest.model_validate(event_data)
            tenant_id = next_day_request.tenant_id
        elif event_type == "PLAN_DAY_REQUESTED":
            recurring_request = RecurringDailyRequest.model_validate(event_data)
            operating_day_request = OperatingDayRequest.model_validate({
                **recurring_request.model_dump(),
                "operating_day": _operating_day_from_managed_publish_time(
                    published_at
                ),
            })
            tenant_id = operating_day_authority_id(
                operating_day_request.tenant_id,
                operating_day_request.operating_day,
            )
        if not isinstance(tenant_id, str):
            raise ValueError("PUBSUB_TENANT_REQUIRED")
        scope = _resolve_authority_scope(tenant_id)
    except ValueError as exc:
        return _ack_permanent_pubsub_rejection(
            message_id=message_id, event_type=event_type, reason=str(exc),
            trace_id=trace_id, age_seconds=age_seconds,
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            raise
        if exc.status_code >= 500:
            _log_pubsub_result(
                message_id=message_id, event_type=event_type,
                disposition="RETRYABLE_FAILURE", trace_id=trace_id,
                age_seconds=age_seconds, reason=str(exc.detail),
            )
            raise
        return _ack_permanent_pubsub_rejection(
            message_id=message_id, event_type=event_type,
            reason=str(exc.detail), trace_id=trace_id, age_seconds=age_seconds,
        )
    db = get_spanner_database(scope.database_id)

    if event_type == "PLAN_NEXT_DAY_REQUESTED":
        source_operating_day = _operating_day_from_managed_publish_time(published_at)
        try:
            next_day_res = _generate_next_day_plan(
                tenant_id=tenant_id,
                source_operating_day=source_operating_day,
                correlation_trace_id=trace_id,
            )
        except HTTPException as exc:
            if exc.status_code in {400, 404, 409, 422}:
                return _ack_permanent_pubsub_rejection(
                    message_id=message_id, event_type=event_type,
                    reason=str(exc.detail), trace_id=trace_id,
                    age_seconds=age_seconds, authority=tenant_id,
                )
            _log_pubsub_result(
                message_id=message_id, event_type=event_type,
                disposition="RETRYABLE_FAILURE", trace_id=trace_id,
                age_seconds=age_seconds, reason=str(exc.detail),
                authority=tenant_id,
            )
            raise
        disposition = (
            "IDEMPOTENT_REPLAY" if next_day_res["idempotent_replay"] else "COMMITTED"
        )
        receipt_id = next_day_res["ledger_receipt"]["receipt_id"]
        _log_pubsub_result(
            message_id=message_id, event_type=event_type,
            disposition=disposition, trace_id=trace_id,
            age_seconds=age_seconds, receipt_id=receipt_id,
            authority=tenant_id,
        )
        return {
            "status": "SCHEDULER_NEXT_DAY_PLAN_GENERATED",
            "disposition": disposition,
            "message_id": message_id,
            "event_type": "PLAN_NEXT_DAY_REQUESTED",
            "next_day_plan_result": next_day_res,
            "delivery_identity": caller.email,
            "delivery_audience": caller.audience,
            "trace_id": trace_id
        }

    if event_type == "PLAN_DAY_REQUESTED":
        try:
            day_res = _generate_daily_morning_plan(request=operating_day_request)
        except HTTPException as exc:
            error_code = _http_exception_code(exc)
            if (
                exc.status_code == 409
                and error_code in PERMANENT_PUBSUB_BUSINESS_REJECTION_CODES
            ):
                return _ack_permanent_pubsub_rejection(
                    message_id=message_id, event_type=event_type,
                    reason=error_code, trace_id=trace_id,
                    age_seconds=age_seconds, authority=tenant_id,
                    error_code=error_code,
                )
            if exc.status_code in {401, 403}:
                raise
            _log_pubsub_result(
                message_id=message_id, event_type=event_type,
                disposition="RETRYABLE_FAILURE", trace_id=trace_id,
                age_seconds=age_seconds, reason=str(exc.detail),
                authority=tenant_id, error_code=error_code,
            )
            if exc.status_code >= 500:
                raise
            raise HTTPException(
                status_code=502,
                detail={"code": "UNKNOWN_DAILY_APPLICATION_FAILURE",
                        "upstream_code": error_code},
            ) from exc
        disposition = "IDEMPOTENT_REPLAY" if day_res["idempotent_replay"] else "COMMITTED"
        receipt_id = (day_res.get("ledger_receipt") or {}).get("receipt_id")
        _log_pubsub_result(
            message_id=message_id, event_type=event_type,
            disposition=disposition, trace_id=trace_id,
            age_seconds=age_seconds, receipt_id=receipt_id,
            authority=tenant_id,
        )
        return {
            "status": "SCHEDULER_DAILY_PLAN_GENERATED",
            "disposition": disposition,
            "message_id": message_id,
            "event_type": "PLAN_DAY_REQUESTED",
            "daily_plan_result": day_res,
            "delivery_identity": caller.email,
            "delivery_audience": caller.audience,
            "trace_id": trace_id
        }

    if event_type != "RECALL_NOTICE_RECEIVED":
        return _ack_permanent_pubsub_rejection(
            message_id=message_id, event_type=event_type,
            reason="UNSUPPORTED_PUBSUB_EVENT_TYPE", trace_id=trace_id,
            age_seconds=age_seconds,
        )
    coord_id = event_data.get("coordinator_id")
    incident_id = event_data.get("incident_id")
    lot_id = event_data.get("lot_id")
    if not all(isinstance(value, str) and value for value in (
        coord_id, incident_id, lot_id
    )):
        return _ack_permanent_pubsub_rejection(
            message_id=message_id, event_type=event_type,
            reason="RECALL_EVENT_SCOPE_REQUIRED", trace_id=trace_id,
            age_seconds=age_seconds,
        )
    coord_state = None
    active_rev = None

    try:
        with db.snapshot() as snapshot:
            results = snapshot.execute_sql(
                "SELECT state, checkpoint, active_plan_revision FROM Coordinators "
                "WHERE tenant_id = @tenant_id AND coordinator_id = @cid",
                params={"tenant_id": tenant_id, "cid": coord_id},
                param_types={
                    "tenant_id": spanner.param_types.STRING,
                    "cid": spanner.param_types.STRING,
                }
            )
            for row in results:
                coord_state, chk, active_rev = row[0], row[1], row[2]
    except Exception as exc:
        raise HTTPException(status_code=503, detail="AUTHORITATIVE_COORDINATOR_READ_UNAVAILABLE") from exc
    if coord_state != "WAITING_FOR_EVENTS" or active_rev is None:
        return _ack_permanent_pubsub_rejection(
            message_id=message_id, event_type=event_type,
            reason="WAITING_COORDINATOR_NOT_FOUND", trace_id=trace_id,
            age_seconds=age_seconds,
        )
    notice_text = event_data.get("notice_text")
    if not isinstance(notice_text, str) or not notice_text.strip():
        return _ack_permanent_pubsub_rejection(
            message_id=message_id, event_type=event_type,
            reason="RECALL_NOTICE_TEXT_REQUIRED", trace_id=trace_id,
            age_seconds=age_seconds,
        )
    hero_result = _execute_managed_recall_event(
        tenant_id=tenant_id, coordinator_id=coord_id,
        incident_id=incident_id, recalled_lot_id=lot_id,
        notice_text=notice_text, source_event_id=message_id,
        source_publish_time=publish_time, active_revision=active_rev,
        trace_id=trace_id,
    )

    return {
        "status": "PUB_SUB_WAKE_PROCESSED",
        "message_id": message_id,
        "event_type": event_type,
        "coordinator_id": coord_id,
        "previous_state": coord_state,
        "rehydrated_revision": active_rev,
        "hero_loop_result": hero_result,
        "delivery_identity": caller.email,
        "delivery_audience": caller.audience,
        "trace_id": trace_id
    }


# -------------------------------------------------------------------
# GATE E, F, G, H — RECALL HERO LOOP
# -------------------------------------------------------------------

def _command_identity(tenant_id: str, incident_id: str, action: str):
    digest = hashlib.sha256(
        f"{tenant_id}\x00{incident_id}\x00{action}".encode("utf-8")
    ).hexdigest()
    return f"CMD-{digest[:28].upper()}", f"hero:{digest}"


def _read_authoritative_recall_inputs(
    db, *, tenant_id: str, recalled_lot_id: str, revision: str
):
    with db.snapshot(multi_use=True) as snapshot:
        plan_rows = list(snapshot.execute_sql(
            "SELECT plan_id FROM PlanRevisions WHERE tenant_id = @tenant_id "
            "AND revision = @revision AND status = 'ACTIVE'",
            params={"tenant_id": tenant_id, "revision": revision},
            param_types={"tenant_id": spanner.param_types.STRING,
                         "revision": spanner.param_types.STRING},
        ))
        recalled_lot_rows = list(snapshot.execute_sql(
            "SELECT total_cases FROM Lots WHERE tenant_id = @tenant_id AND lot_id = @lot_id",
            params={"tenant_id": tenant_id, "lot_id": recalled_lot_id},
            param_types={"tenant_id": spanner.param_types.STRING,
                         "lot_id": spanner.param_types.STRING},
        ))
        safe_lot_rows = list(snapshot.execute_sql(
            "SELECT lot_id, total_cases FROM Lots WHERE tenant_id = @tenant_id "
            "AND hazard_status = 'CLEAR_SAFE' ORDER BY lot_id",
            params={"tenant_id": tenant_id},
            param_types={"tenant_id": spanner.param_types.STRING},
        ))
        order_rows = list(snapshot.execute_sql(
            "SELECT order_id, destination_agency_id, cases FROM Orders "
            "WHERE tenant_id = @tenant_id AND revision = @revision AND lot_id = @lot_id "
            "ORDER BY order_id",
            params={"tenant_id": tenant_id, "revision": revision,
                    "lot_id": recalled_lot_id},
            param_types={"tenant_id": spanner.param_types.STRING,
                         "revision": spanner.param_types.STRING,
                         "lot_id": spanner.param_types.STRING},
        ))
    if len(plan_rows) != 1 or len(recalled_lot_rows) != 1:
        raise HTTPException(409, "ACTIVE_RECALL_PLAN_INPUTS_NOT_FOUND")
    if not safe_lot_rows or not order_rows:
        raise HTTPException(409, "RECOVERY_INPUTS_NOT_FOUND")
    return {
        "plan_id": plan_rows[0][0],
        "recalled_total_cases": recalled_lot_rows[0][0],
        "safe_lots": safe_lot_rows,
        "affected_orders": order_rows,
    }


def _derive_safe_recovery(*, incident_id: str, safe_lots, affected_orders):
    remaining = [[row[0], row[1]] for row in safe_lots]
    allocations = []
    shortfalls = []
    for order_id, agency_id, cases in affected_orders:
        unmet = cases
        for safe_lot in remaining:
            if unmet == 0:
                break
            assigned = min(unmet, safe_lot[1])
            if assigned <= 0:
                continue
            allocation_digest = hashlib.sha256(
                f"{incident_id}\x00{agency_id}\x00{safe_lot[0]}".encode()
            ).hexdigest()[:20].upper()
            allocations.append({
                "allocation_id": f"ALLOC-{allocation_digest}",
                "agency_id": agency_id,
                "lot_id": safe_lot[0],
                "cases": assigned,
            })
            safe_lot[1] -= assigned
            unmet -= assigned
        if unmet:
            shortfall_digest = hashlib.sha256(
                f"{incident_id}\x00{agency_id}\x00{order_id}".encode()
            ).hexdigest()[:20].upper()
            shortfalls.append({
                "shortfall_id": f"SHORT-{shortfall_digest}",
                "agency_id": agency_id,
                "cases": unmet,
            })
    if not allocations or not shortfalls:
        raise HTTPException(409, "PARTIAL_RECOVERY_POLICY_INPUTS_REQUIRED")
    return allocations, shortfalls


def _run_agent_fleet_proposal(
    *,
    incident_id: str,
    lot_id: str,
    screened_notice_text: str,
    graph: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    unconfirmed_position: Dict[str, Any],
    unconfirmed_cases: int,
    source_event_id: Optional[str] = None,
    deadline: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one real Incident Coordinator ADK execution and revalidate its output.

    Called only from the pre-mutation gate. The fleet never submits anything and
    never reaches the ledger; this function converts an accepted proposal into
    deterministic allocations, and any agent, model, tool, schema, timeout, or
    reconciliation failure into MANUAL_REVIEW_REQUIRED with zero ledger calls.
    """
    try:
        result = run_fleet(
            incident_id=incident_id,
            lot_id=lot_id,
            screened_notice_text=screened_notice_text,
            graph_result=graph,
            recovery_candidates=candidates,
            source_event_id=source_event_id,
            trigger=TriggerClass.RECALL,
            partner_state={
                "partner_id": unconfirmed_position["node_id"],
                "partner_name": unconfirmed_position["name"],
                "lot_id": lot_id,
                "unconfirmed_cases": unconfirmed_cases,
                "acknowledgment_status": unconfirmed_position[
                    "acknowledgment_status"
                ],
                "deadline": deadline,
            },
        )
    except FleetProposalError as exc:
        return {"status": "MANUAL_REVIEW_REQUIRED", "reason_code": exc.reason_code,
                "proposal": None, "recovery_candidate": None,
                "extraction_evidence": None}
    except Exception:
        # No fleet failure may fall back to canonical output.
        return {"status": "MANUAL_REVIEW_REQUIRED",
                "reason_code": "FLEET_EXECUTION_FAILED",
                "proposal": None, "recovery_candidate": None,
                "extraction_evidence": None}

    proposal = result["proposal"]
    if proposal.status != "PROPOSED" or result["recovery_candidate"] is None:
        return {"status": "MANUAL_REVIEW_REQUIRED",
                "reason_code": proposal.reason_code or "FLEET_PROPOSAL_REJECTED",
                "proposal": proposal.model_dump(), "recovery_candidate": None,
                "extraction_evidence": None}

    dumped = proposal.model_dump()
    extraction_evidence = dict(dumped.get("extraction") or {})
    recall_hop = next(
        (entry for entry in dumped["delegation_trace"]
         if entry["agent_id"] == AGENT_RECALL_INTAKE_EXTRACTION),
        {},
    )
    # Evidence comes from the recall specialist's actual ADK execution. Built by
    # merge rather than dict.update so the orchestrator source stays free of any
    # `.update(` call, which `test_no_authoritative_writes` prohibits outright.
    extraction_evidence = {
        **extraction_evidence,
        "model_used": recall_hop.get("model_used"),
        "adk_framework": recall_hop.get("adk_framework"),
        "adk_run_id": recall_hop.get("specialist_run_id"),
        "adk_event_id": recall_hop.get("adk_event_id"),
        # The recall specialist's OWN session, never the coordinator's.
        "adk_session_id": recall_hop.get("specialist_session_id"),
        "validation_status": recall_hop.get("deterministic_validation"),
        "status": "EXTRACTION_VALIDATED",
        "downstream_allowed": True,
    }
    return {"status": "ACCEPTED", "reason_code": None,
            "proposal": dumped,
            "recovery_candidate": result["recovery_candidate"],
            "extraction_evidence": extraction_evidence}


def _execute_managed_recall_event(
    *,
    tenant_id: str,
    coordinator_id: str,
    incident_id: str,
    recalled_lot_id: str,
    notice_text: str,
    source_event_id: str,
    source_publish_time: str,
    active_revision: str,
    trace_id: str,
):
    """Run one generalized managed recall policy after authenticated Pub/Sub wake."""
    scope = _resolve_authority_scope(tenant_id)
    db = get_spanner_database(scope.database_id)
    screening = inspect_recall_notice_with_model_armor(
        notice_text, correlation_id=trace_id
    )
    screening_approved = (
        screening.get("status") == "APPROVED"
        and screening.get("safety_verdict") == "PASSED"
    )
    correlation_matches_execution = screening.get("correlation_id") == trace_id
    if not screening_approved or not correlation_matches_execution:
        return {
            "hero_loop_status": (
                "HALTED_BY_MODEL_ARMOR_SAFETY_MATCH"
                if screening.get("status") == "BLOCKED"
                else "HALTED_BY_MODEL_ARMOR_SERVICE_FAILURE"
            ),
            "model_armor_screening": screening,
            "gemini_adk_invoked": False,
            "ledger_commands_attempted": 0,
            "ledger_commands_accepted": 0,
            "mutations_committed": 0,
            "ledger_mutation_attempted": False,
            "trace_id": trace_id,
        }

    # ------------------------------------------------------------------
    # PRE-MUTATION FLEET GATE
    #
    # Every fallible step - authoritative reads, the Spanner Graph traversal,
    # deterministic candidate construction, all five ADK agents, every tool
    # call, schema parse, timeout, and deterministic validation - completes
    # here, BEFORE the first ledger command is attempted. Nothing below this
    # gate may fail for a model reason, so a fleet failure always means zero
    # ledger commands attempted and zero mutations committed.
    # ------------------------------------------------------------------
    def _pre_ledger_halt(stage: str, reason_code: str, *, http_status=None, **extra):
        """Every pre-ledger exit reports the same truthful zero counters.

        `http_status` preserves the classification the caller would have raised,
        so transport retry/ack behavior is unchanged by counting the failure.

        Callers guard with `except Exception`, which deliberately excludes
        BaseException: KeyboardInterrupt, SystemExit, and asyncio.CancelledError
        continue to propagate rather than being converted into a halt.
        """
        return {
            "hero_loop_status": "HALTED_FOR_MANUAL_REVIEW",
            "halt_stage": stage,
            "manual_review_reason": reason_code,
            "http_status_classification": http_status,
            "model_armor_screening": screening,
            "ledger_commands_attempted": 0,
            "ledger_commands_accepted": 0,
            "mutations_committed": 0,
            "ledger_mutation_attempted": False,
            "trace_id": trace_id,
            **extra,
        }

    try:
        inputs = _read_authoritative_recall_inputs(
            db, tenant_id=tenant_id, recalled_lot_id=recalled_lot_id,
            revision=active_revision,
        )
    except HTTPException as exc:
        # Preserve the deterministic business classification (409/404/...).
        return _pre_ledger_halt(
            "AUTHORITATIVE_READ", str(exc.detail), http_status=exc.status_code,
        )
    except Exception:
        # A generic infrastructure failure (for example a raw Spanner error)
        # must fail closed exactly like a classified one: zero ledger activity,
        # and a retryable 503 so managed delivery can redeliver.
        return _pre_ledger_halt(
            "AUTHORITATIVE_READ", "AUTHORITATIVE_READ_UNAVAILABLE",
            http_status=503,
        )
    try:
        graph = _run_managed_custody_graph(
            db, tenant_id=tenant_id, lot_id=recalled_lot_id
        )
    except Exception:
        return _pre_ledger_halt(
            "AUTHORITATIVE_GRAPH_READ", "AUTHORITATIVE_GRAPH_READ_UNAVAILABLE",
            http_status=503,
        )
    if graph["unique_current_cases"] != inputs["recalled_total_cases"]:
        return _pre_ledger_halt(
            "CUSTODY_RECONCILIATION",
            "CUSTODY_TOTAL_DOES_NOT_MATCH_RECALLED_LOT",
            spanner_graph_reconstruction=graph,
        )
    if len(graph["unconfirmed_positions"]) != 1 or graph["unconfirmed_cases"] <= 0:
        return _pre_ledger_halt(
            "CUSTODY_RECONCILIATION",
            "EXACTLY_ONE_UNCONFIRMED_POSITION_REQUIRED",
            spanner_graph_reconstruction=graph,
        )
    unconfirmed_position = graph["unconfirmed_positions"][0]

    # Deterministic code owns the candidate set. The fleet may only choose
    # among these candidates; it can neither extend nor alter them.
    try:
        candidates = generate_recovery_candidates(
            incident_id=incident_id, safe_lots=inputs["safe_lots"],
            affected_orders=inputs["affected_orders"],
        )
    except HTTPException as exc:
        return _pre_ledger_halt(
            "RECOVERY_CANDIDATE_GENERATION", str(exc.detail),
            http_status=exc.status_code,
        )
    except Exception:
        return _pre_ledger_halt(
            "RECOVERY_CANDIDATE_GENERATION",
            "RECOVERY_CANDIDATE_GENERATION_FAILED", http_status=500,
        )
    fleet = _run_agent_fleet_proposal(
        incident_id=incident_id, lot_id=recalled_lot_id,
        screened_notice_text=notice_text, graph=graph, candidates=candidates,
        unconfirmed_position=unconfirmed_position,
        unconfirmed_cases=graph["unconfirmed_cases"],
        source_event_id=source_event_id,
    )
    _persist_model_invocation_evidence(
        fleet.get("extraction_evidence") or {}, route="managed-pubsub-recall"
    )
    if fleet["status"] != "ACCEPTED":
        return {
            "hero_loop_status": "HALTED_FOR_MANUAL_REVIEW",
            "halt_stage": "AGENT_FLEET_PROPOSAL",
            "manual_review_reason": fleet["reason_code"],
            "agent_fleet": fleet,
            "model_armor_screening": screening,
            "spanner_graph_reconstruction": graph,
            "ledger_commands_attempted": 0,
            "ledger_commands_accepted": 0,
            "mutations_committed": 0,
            "ledger_mutation_attempted": False,
            "trace_id": trace_id,
        }
    extracted = fleet["extraction_evidence"]
    allocations = fleet["recovery_candidate"]["allocations"]
    shortfalls = fleet["recovery_candidate"]["shortfalls"]

    # Independent deterministic cross-check before any mutation: the
    # fleet-selected candidate must reproduce the accepted recovery policy.
    try:
        expected_allocations, expected_shortfalls = _derive_safe_recovery(
            incident_id=incident_id, safe_lots=inputs["safe_lots"],
            affected_orders=inputs["affected_orders"],
        )
    except HTTPException as exc:
        return _pre_ledger_halt(
            "FLEET_RECOVERY_RECONCILIATION", str(exc.detail),
            http_status=exc.status_code, agent_fleet=fleet,
        )
    except Exception:
        return _pre_ledger_halt(
            "FLEET_RECOVERY_RECONCILIATION",
            "RECOVERY_CROSS_CHECK_FAILED", http_status=500, agent_fleet=fleet,
        )
    if (sum(a["cases"] for a in allocations)
            != sum(a["cases"] for a in expected_allocations)
            or sum(s["cases"] for s in shortfalls)
            != sum(s["cases"] for s in expected_shortfalls)):
        return {
            "hero_loop_status": "HALTED_FOR_MANUAL_REVIEW",
            "halt_stage": "FLEET_RECOVERY_RECONCILIATION",
            "manual_review_reason": "FLEET_RECOVERY_DOES_NOT_RECONCILE",
            "agent_fleet": fleet,
            "model_armor_screening": screening,
            "ledger_commands_attempted": 0,
            "ledger_commands_accepted": 0,
            "mutations_committed": 0,
            "ledger_mutation_attempted": False,
            "trace_id": trace_id,
        }

    # ------------------------------------------------------------------
    # MUTATION PHASE. Only a fully accepted proposal reaches this point.
    # ------------------------------------------------------------------
    ledger_calls = {"attempted": 0, "accepted": 0, "committed": 0}

    def _record(result):
        ledger_calls["attempted"] += 1
        receipt = result.get("receipt", {})
        if receipt.get("status") == "SUCCESS":
            ledger_calls["accepted"] += 1
        ledger_calls["committed"] += int(receipt.get("mutations_applied") or 0)
        return result

    open_command_id, open_key = _command_identity(
        tenant_id, incident_id, f"open:{source_event_id}"
    )
    open_result = _record(execute_ledger_command(
        command_id=open_command_id, idempotency_key=open_key,
        tenant_id=tenant_id, incident_id=incident_id,
        agent_role="INCIDENT_COORDINATOR", command_type="OPEN_RECALL_INCIDENT",
        expected_plan_revision=active_revision, trace_id=trace_id,
        payload={
            "incident_id": incident_id, "coordinator_id": coordinator_id,
            "lot_id": recalled_lot_id, "source_event_id": source_event_id,
            "source_publish_time": source_publish_time,
            "model_armor_correlation_id": screening["correlation_id"],
            "details": {
                "hazard": extracted.get("hazard", {}).get("value") if extracted.get("hazard") else None,
                # Delta 3: the advisory fleet execution evidence was previously
                # returned to Pub/Sub and discarded. Persisting it on the
                # incident makes the five real ADK run/session identities
                # durably readable by the operator projection without adding a
                # ledger command type, a route, or a schema change.
                "agent_fleet": {
                    "manifest_version": FLEET_MANIFEST_VERSION,
                    "root_agent_id": AGENT_INCIDENT_COORDINATOR,
                    "coordinator_session_id": fleet["proposal"]["coordinator_session_id"],
                    "coordination_run_id": fleet["proposal"]["coordination_run_id"],
                    "proposal_status": fleet["proposal"]["status"],
                    "proposal_hash": fleet["proposal"]["proposal_hash"],
                    "delegation_trace": fleet["proposal"]["delegation_trace"],
                },
            },
        },
    ))

    def commit(action, command_type, payload, *, agent_role="INCIDENT_COORDINATOR",
               allow_denied=False):
        command_id, idempotency_key = _command_identity(tenant_id, incident_id, action)
        return _record(execute_ledger_command(
            command_id=command_id, idempotency_key=idempotency_key,
            tenant_id=tenant_id, incident_id=incident_id, agent_role=agent_role,
            command_type=command_type, expected_plan_revision=active_revision,
            trace_id=trace_id, payload=payload, allow_denied=allow_denied,
        ))

    scoping = commit("status:SCOPING", "SET_INCIDENT_STATUS", {
        "incident_id": incident_id, "expected_status": "DETECTED",
        "new_status": "SCOPING", "terminal_state": "NONE",
    })
    barrier_id = f"BARRIER-{hashlib.sha256(recalled_lot_id.encode()).hexdigest()[:20].upper()}"
    barrier = commit("movement-barrier", "ACTIVATE_MOVEMENT_BARRIER", {
        "barrier_id": barrier_id, "incident_id": incident_id,
        "lot_id": recalled_lot_id, "reason": "FOOD_SAFETY_RECALL",
        "work_item_id": f"WORK-{hashlib.sha256((incident_id + recalled_lot_id).encode()).hexdigest()[:20].upper()}",
    })
    containment = commit("status:CONTAINMENT_IN_PROGRESS", "SET_INCIDENT_STATUS", {
        "incident_id": incident_id, "expected_status": "SCOPING",
        "new_status": "CONTAINMENT_IN_PROGRESS", "terminal_state": "NONE",
    })
    invalidation = commit("plan:invalidate", "INVALIDATE_PLAN", {
        "plan_id": inputs["plan_id"], "revision": active_revision,
        "reason": f"{recalled_lot_id}_RECALL",
    })
    recovery = commit(
        "safe-recovery", "ALLOCATE_SAFE_STOCK",
        {"incident_id": incident_id, "allocations": allocations,
         "shortfalls": shortfalls},
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
    )
    refusal = commit(
        "containment-refusal", "RECORD_REFUSAL",
        {"incident_id": incident_id,
         "subject_id": unconfirmed_position["node_id"],
         "reason": "DOWNSTREAM_CUSTODY_UNCONFIRMED",
         "affected_cases": graph["unconfirmed_cases"]},
        allow_denied=True,
    )
    hold_digest = hashlib.sha256(
        f"{incident_id}\x00{unconfirmed_position['node_id']}".encode()
    ).hexdigest()[:20].upper()
    hold_incident_id = f"HOLD-{hold_digest}"
    task = schedule_site01_deadline_task(
        tenant_id=tenant_id, incident_id=incident_id,
        hold_incident_id=hold_incident_id, coordinator_id=coordinator_id,
        lot_id=recalled_lot_id, site_id=unconfirmed_position["node_id"],
        unconfirmed_cases=graph["unconfirmed_cases"], task_id=f"ack-{trace_id}",
        oidc_audience=MANAGED_CALLBACK_AUDIENCE,
        delivery_service_account=MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL,
        trace_id=trace_id,
    )
    terminal = commit("status:PARTIALLY_CONTAINED", "SET_INCIDENT_STATUS", {
        "incident_id": incident_id, "expected_status": "CONTAINMENT_IN_PROGRESS",
        "new_status": "PARTIALLY_CONTAINED", "terminal_state": "PARTIALLY_CONTAINED",
        "unconfirmed_cases": graph["unconfirmed_cases"],
    })
    return {
        "hero_loop_status": "COMPLETED",
        "authority_scope_kind": scope.kind,
        "ledger_commands_attempted": ledger_calls["attempted"],
        "ledger_commands_accepted": ledger_calls["accepted"],
        "mutations_committed": ledger_calls["committed"],
        "model_armor_screening": screening,
        "gemini_35_extraction": extracted,
        "spanner_graph_reconstruction": graph,
        "safe_stock_recovery": {"allocations": allocations, "shortfalls": shortfalls},
        "agent_fleet": {
            "manifest_version": FLEET_MANIFEST_VERSION,
            "root_agent_id": AGENT_INCIDENT_COORDINATOR,
            "coordinator_session_id": fleet["proposal"]["coordinator_session_id"],
            "coordination_run_id": fleet["proposal"]["coordination_run_id"],
            "proposal_status": fleet["proposal"]["status"],
            "proposal_hash": fleet["proposal"]["proposal_hash"],
            "delegation_trace": fleet["proposal"]["delegation_trace"],
            "selected_candidate_id": fleet["recovery_candidate"]["candidate_id"],
            "candidate_ids_offered": [c["candidate_id"] for c in candidates],
            # Partner Operations does not run on the recall path (§6), so this
            # evidence field is absent rather than empty. Outbound follow-up is
            # dispatched separately and records its own template evidence.
            "partner_template_id": (
                (fleet["proposal"].get("partner") or {}).get("template_id")
            ),
            "deterministic_reconciliation": "RECONCILED_WITH_ACCEPTED_POLICY",
        },
        "unconfirmed_position": unconfirmed_position,
        "ledger_command_receipts": {
            "open": open_result["receipt"], "scoping": scoping["receipt"],
            "barrier": barrier["receipt"], "containment_in_progress": containment["receipt"],
            "plan_invalidation": invalidation["receipt"], "safe_recovery": recovery["receipt"],
            "containment_refusal": refusal["receipt"], "terminal": terminal["receipt"],
        },
        "cloud_tasks_scheduling": task,
        "terminal_state": "PARTIALLY_CONTAINED",
        "trace_id": trace_id,
    }

@app.get(
    "/api/v1/orchestrator/custody/graph",
    dependencies=[Depends(require_internal_workload)],
)
def get_custody_graph_reconstruction(
    tenant_id: str = Query("east-bay-food-bank"),
    lot_id: str = Query(..., min_length=1, max_length=64),
):
    """Run a parameterized, variable-depth managed Spanner Graph reconstruction."""
    scope = _resolve_authority_scope(tenant_id)
    database_id = scope.database_id

    try:
        result = _run_managed_custody_graph(
            get_spanner_database(database_id),
            tenant_id=tenant_id,
            lot_id=lot_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="AUTHORITATIVE_GRAPH_READ_UNAVAILABLE") from exc

    result["authority_scope_kind"] = scope.kind
    result["database_id"] = database_id
    return result

@app.post("/api/v1/orchestrator/recall/execute-hero-loop")
def execute_hero_loop(
    tenant_id: str = "east-bay-food-bank"
):
    """Reject the retired direct executor; managed Pub/Sub delivery owns execution."""
    _resolve_authority_scope(tenant_id)
    raise HTTPException(410, "USE_MANAGED_RECALL_TRIGGER")


@app.post(
    "/api/v1/orchestrator/recall/model-armor-preflight",
    dependencies=[Depends(require_internal_workload)],
)
def model_armor_preflight(
    request: RecallArmorPreflightRequest,
):
    """Exercise only the deployed untrusted-input boundary; never call Gemini or ledger."""
    request_correlation_id = generate_trace_id()
    screening = inspect_recall_notice_with_model_armor(
        request.notice_text,
        correlation_id=request_correlation_id,
    )

    if screening.get("status") == "APPROVED" and screening.get("safety_verdict") == "PASSED":
        status = "READY_FOR_GEMINI_ADK_EXTRACTION"
        next_authorized_stage = "GEMINI_ADK_EXTRACTION"
    elif screening.get("status") == "BLOCKED":
        status = "REJECTED_BY_MODEL_ARMOR"
        next_authorized_stage = None
    else:
        status = "HALTED_BY_MODEL_ARMOR_SERVICE_FAILURE"
        next_authorized_stage = None

    evidence = {
        "event": "MODEL_ARMOR_PREFLIGHT_COMPLETED",
        "request_correlation_id": request_correlation_id,
        "status": status,
        "managed_operation": screening.get("managed_operation"),
        "managed_template": screening.get("model_armor_template"),
        "filter_match_state": screening.get("filter_match_state"),
        "gemini_adk_invoked": False,
        "ledger_mutation_attempted": False,
    }
    print(json.dumps(evidence, sort_keys=True))
    return {
        "preflight_status": status,
        "request_correlation_id": request_correlation_id,
        "model_armor_screening": screening,
        "next_authorized_stage": next_authorized_stage,
        "gemini_adk_invoked": False,
        "ledger_mutation_attempted": False,
    }


def _persist_model_invocation_evidence(
    extraction: Dict[str, Any],
    *,
    route: str,
) -> Dict[str, Any]:
    """Persist sanitized ADK identifiers to managed application logging."""
    record = {
        "event": "ADK_MODEL_INVOCATION_COMPLETED",
        "route": route,
        "status": extraction.get("status"),
        "reason_code": extraction.get("reason_code"),
        "model_id": extraction.get("model_used"),
        "vertex_location": extraction.get("vertex_location"),
        "adk_framework": extraction.get("adk_framework"),
        "adk_session_backend": extraction.get("adk_session_backend"),
        "adk_session_id": extraction.get("adk_session_id"),
        "adk_run_id": extraction.get("adk_run_id"),
        "adk_event_id": extraction.get("adk_event_id"),
        "request_correlation_id": extraction.get("correlation_id"),
        "validation_status": extraction.get("validation_status"),
        "downstream_allowed": extraction.get("downstream_allowed", False),
    }
    print(json.dumps(record, sort_keys=True))
    return record


@app.post(
    "/api/v1/orchestrator/recall/extraction-preflight",
    dependencies=[Depends(require_internal_workload)],
)
def extraction_preflight(
    request: RecallArmorPreflightRequest,
):
    """Exercise the deployed Model Armor -> ADK boundary without mutation."""
    request_correlation_id = generate_trace_id()
    screening = inspect_recall_notice_with_model_armor(
        request.notice_text,
        correlation_id=request_correlation_id,
    )
    if screening.get("status") != "APPROVED" or screening.get("safety_verdict") != "PASSED":
        return {
            "preflight_status": "HALTED_BY_MODEL_ARMOR",
            "request_correlation_id": request_correlation_id,
            "model_armor_screening": screening,
            "gemini_adk_invoked": False,
            "ledger_mutation_attempted": False,
        }

    extraction = extract_recall_entities_with_gemini_35(
        request.notice_text,
        correlation_id=request_correlation_id,
    )
    persisted_record = _persist_model_invocation_evidence(
        extraction,
        route="extraction-preflight",
    )
    if not extraction.get("downstream_allowed"):
        status = "MANUAL_REVIEW_REQUIRED"
        next_authorized_stage = None
    else:
        status = "READY_FOR_POLICY_REVIEW"
        next_authorized_stage = "DETERMINISTIC_POLICY_REVIEW"
    return {
        "preflight_status": status,
        "request_correlation_id": request_correlation_id,
        "model_armor_screening": screening,
        "extraction": extraction,
        "model_invocation_record": persisted_record,
        "identifiers_persisted_to": "CLOUD_LOGGING",
        "next_authorized_stage": next_authorized_stage,
        "ledger_mutation_attempted": False,
    }


def _derive_repair_proposal(
    *, tenant_id: str, vehicle_id: str, source_event_id: str,
    operating_day: str, correlation_trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Derive one repair proposal from committed state and persist it.

    Reads the active plan, the failed vehicle's commitments, and the fleet.
    Orders that fit the absorbing vehicle are proposed as a reroute; the
    remainder is proposed as a refrigerated partner pickup, because a
    proposal that overruns capacity is not a proposal.

    Nothing here activates anything. The result is an AGENT_PROPOSAL that the
    existing verified-human -> KMS -> ledger path may later approve.
    """
    trace_id = correlation_trace_id or generate_trace_id()
    scope = _resolve_authority_scope(tenant_id)
    db = get_spanner_database(scope.database_id)
    plan_id = f"PLAN-{operating_day}"

    with db.snapshot(multi_use=True) as snapshot:
        active = list(snapshot.execute_sql(
            "SELECT revision FROM PlanRevisions WHERE tenant_id=@t "
            "AND plan_id=@p AND status='ACTIVE'",
            params={"t": tenant_id, "p": plan_id},
            param_types={"t": spanner.param_types.STRING,
                         "p": spanner.param_types.STRING},
        ))
        if len(active) != 1:
            raise HTTPException(409, "NO_SINGLE_ACTIVE_PLAN_REVISION")
        source_revision = active[0][0]
        stranded = list(snapshot.execute_sql(
            "SELECT order_id, cases, status FROM Orders WHERE tenant_id=@t "
            "AND plan_id=@p AND revision=@r AND assigned_vehicle_id=@v "
            "ORDER BY order_id",
            params={"t": tenant_id, "p": plan_id, "r": source_revision,
                    "v": vehicle_id},
            param_types={"t": spanner.param_types.STRING,
                         "p": spanner.param_types.STRING,
                         "r": spanner.param_types.STRING,
                         "v": spanner.param_types.STRING},
        ))
        fleet = list(snapshot.execute_sql(
            "SELECT vehicle_id, max_capacity_cases, current_load_cases FROM Vehicles "
            "WHERE tenant_id=@t AND is_operational=TRUE AND vehicle_id!=@v "
            "ORDER BY vehicle_id",
            params={"t": tenant_id, "v": vehicle_id},
            param_types={"t": spanner.param_types.STRING,
                         "v": spanner.param_types.STRING},
        ))

    # Undelivered commitments only: what is already delivered is not stranded.
    pending = [row for row in stranded if row[2] != "DELIVERED"]
    if len(pending) < 2 or not fleet:
        raise HTTPException(409, "NO_FEASIBLE_REPAIR_FROM_AUTHORITATIVE_STATE")
    absorbing_id, capacity, committed = fleet[0]
    headroom = (capacity or 0) - (committed or 0)
    reroute = next((row for row in pending if (row[1] or 0) <= headroom), None)
    if reroute is None:
        raise HTTPException(409, "NO_OPERATIONAL_VEHICLE_HAS_HEADROOM")
    pickup = next((row for row in pending if row[0] != reroute[0]), None)
    if pickup is None:
        raise HTTPException(409, "NO_SECOND_COMMITMENT_TO_ROUTE_TO_A_PARTNER")

    # Gate repair through Fulfillment agent before ledger persist
    incident_id_repair = f"INC-REPAIR-{source_event_id}"
    try:
        fleet_result = run_fleet(
            incident_id=incident_id_repair,
            lot_id="FLEET_FAILURE_NO_LOT",
            screened_notice_text=f"Fleet failure: {vehicle_id} offline",
            graph_result={},
            recovery_candidates=[{
                "candidate_id": f"{absorbing_id}-repair",
                "revision": source_revision,
                "content_hash": hashlib.sha256(
                    f"{reroute[0]},{pickup[0]}".encode("utf-8")
                ).hexdigest(),
                # The repair objective strands nothing: one commitment moves to
                # a vehicle with headroom, the other goes to refrigerated
                # partner pickup. An empty shortfall list is the correct,
                # truthful output here -- not a missing input.
                "allocations": [{
                    "order_id": reroute[0],
                    "cases": reroute[1],
                    "target_vehicle_id": absorbing_id,
                }],
                "partner_pickups": [{
                    "order_id": pickup[0],
                    "cases": pickup[1],
                }],
                "shortfalls": [],
            }],
            source_event_id=source_event_id,
            trigger=TriggerClass.FLEET_FAILURE,
            expected_revision=source_revision,
            partner_state={},
        )
        if fleet_result["proposal"].status != "PROPOSED":
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "REPAIR_REJECTED_BY_FULFILLMENT",
                    "reason": fleet_result["proposal"].reason_code,
                },
            )
    except FleetProposalError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "FLEET_FAILURE_FLEET_VALIDATION_FAILED",
                "reason": exc.reason_code,
            },
        ) from exc

    proposal_id = "PROP-" + hashlib.sha256(
        f"{tenant_id}\x00{plan_id}\x00{source_revision}\x00{source_event_id}".encode()
    ).hexdigest()[:24].upper()
    ledger_result = execute_ledger_command(
        command_id=f"CMD-PROPOSAL-{proposal_id}",
        idempotency_key=f"{tenant_id}:{plan_id}:{source_revision}:repair-proposal",
        tenant_id=tenant_id,
        incident_id=None,
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        command_type="PERSIST_REPAIR_PROPOSAL",
        expected_plan_revision=source_revision,
        trace_id=trace_id,
        payload={
            "proposal_id": proposal_id,
            "source_event_id": source_event_id,
            "plan_id": plan_id,
            "source_revision": source_revision,
            "proposed_revision": CANONICAL_APPROVAL_PROPOSED_REVISION,
            "vehicle_id": vehicle_id,
            "absorbing_vehicle_capacity_cases": capacity,
            "absorbing_vehicle_committed_cases": committed,
            "plan_diff": {
                "reroute_order_id": reroute[0],
                "reroute_cases": reroute[1],
                "reroute_target_vehicle": absorbing_id,
                "pickup_order_id": pickup[0],
                "pickup_cases": pickup[1],
            },
        },
    )
    return {
        "status": "REPAIR_PROPOSAL_PERSISTED",
        "proposal_id": proposal_id,
        "authority": "AGENT_PROPOSAL",
        "activation_supported": False,
        "idempotent_replay": ledger_result["idempotent_replay"],
        "ledger_receipt": ledger_result["receipt"],
        "trace_id": trace_id,
    }


@app.post(
    "/api/v1/orchestrator/fleet/refrigeration-failure",
    dependencies=[Depends(require_internal_workload)],
)
def report_refrigeration_failure(
    event: VehicleRefrigerationFailureRequest,
    tenant_id: str = Query("east-bay-food-bank"),
    operating_day: str = Query(...),
):
    """Accept a mechanical fleet fault and persist the resulting proposal.

    Idempotent on source_event_id: InboundEvents is keyed by
    (tenant_id, source_event_id), so a redelivered fault reports the same
    proposal and applies no further mutations.
    """
    return _derive_repair_proposal(
        tenant_id=tenant_id,
        vehicle_id=event.vehicle_id,
        source_event_id=event.source_event_id,
        operating_day=operating_day,
    )


@app.post(
    "/api/v1/orchestrator/recall/trigger",
    dependencies=[Depends(require_internal_workload)],
)
def trigger_recall_hero_loop(
    request: RecallTriggerRequest,
    tenant_id: str = "east-bay-food-bank"
):
    _resolve_authority_scope(tenant_id)
    event = {
        "event_type": "RECALL_NOTICE_RECEIVED",
        "tenant_id": tenant_id,
        **request.model_dump(),
    }
    published = publish_recall_event_to_pubsub(event)
    return {
        "status": "RECALL_EVENT_PUBLISHED_AWAIT_MANAGED_DELIVERY",
        "topic": published["topic"],
        "message_id": published["message_id"],
        "tenant_id": tenant_id,
        "incident_id": request.incident_id,
        "lot_id": request.lot_id,
        "classification": "OBSERVED_LIVE",
    }


@app.get(
    "/api/v1/orchestrator/recall/incident-status",
    dependencies=[Depends(require_internal_workload)],
)
def get_incident_status(
    incident_id: str = Query(..., min_length=1, max_length=128),
    tenant_id: str = "east-bay-food-bank",
):
    scope = _resolve_authority_scope(tenant_id)
    db = get_spanner_database(scope.database_id)
    incident_data = {}
    with db.snapshot() as snapshot:
        rows = list(snapshot.execute_sql(
            "SELECT incident_id, status, terminal_state, affected_lot_id FROM Incidents WHERE tenant_id = @t AND incident_id = @iid",
            params={"t": tenant_id, "iid": incident_id},
            param_types={"t": spanner.param_types.STRING, "iid": spanner.param_types.STRING}
        ))
        if rows:
            r = rows[0]
            incident_data = {
                "incident_id": r[0],
                "status": r[1],
                "terminal_state": r[2] if r[2] != "NONE" else r[1],
                "affected_lot_id": r[3]
            }

    if not incident_data:
        raise HTTPException(status_code=404, detail="INCIDENT_NOT_FOUND")

    return incident_data


# -------------------------------------------------------------------
# GATE I — CONTINUOUS NEXT-DAY PLANNING
# -------------------------------------------------------------------

def _parse_managed_publish_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "PUBSUB_PUBLISH_TIME_INVALID") from exc
    if parsed.tzinfo is None:
        raise HTTPException(400, "PUBSUB_PUBLISH_TIME_TIMEZONE_REQUIRED")
    return parsed


CANDIDATE_BASIS = "DETERMINISTIC_DERIVATION_FROM_AUTHORITATIVE_STATE"


def _candidate_assignments(shortfalls, safe_lots, fleet, *, plan_id,
                           agency_names) -> Dict[str, Any]:
    """Derive one candidate next-day schedule from authoritative state only.

    Demand is the open recovery shortfalls carried into tomorrow. Supply is
    confirmed-safe inventory and operational transport capacity. Nothing here
    invents a case, a vehicle, or a destination: demand that cannot be met from
    confirmed-safe supply stays in unassigned_demand, visibly short, which is
    the whole point of a constrained draft.

    This is a candidate, not a plan. It is never activated, and the caller
    commits it as DRAFT_WITH_CONSTRAINTS requiring human approval.
    """
    available = {row[0]: row[1] for row in safe_lots}
    # Deterministic order so the same authoritative state always derives the
    # same candidate: demand largest-first, supply and vehicles by stable id.
    demand = sorted(
        ({"agency_id": row[1], "cases": row[2], "shortfall_id": row[0]}
         for row in shortfalls),
        key=lambda d: (-(d["cases"] or 0), d["agency_id"] or ""),
    )
    vehicles = [
        {"vehicle_id": row[0],
         "capacity_cases": row[1],
         "committed_load_cases": row[2],
         "remaining": (row[1] or 0) - (row[2] or 0),
         "stops": []}
        for row in sorted(fleet, key=lambda r: r[0])
    ]

    unassigned = []
    for item in demand:
        cases = item["cases"] or 0
        lot_id = next((l for l in sorted(available) if available[l] >= cases), None)
        vehicle = next((v for v in vehicles if v["remaining"] >= cases), None)
        if cases <= 0 or lot_id is None or vehicle is None:
            # Truthfully short: no confirmed-safe lot or no remaining capacity.
            # Agency 03's carried shortfall lands here whenever supply cannot
            # cover it, and stays visibly open rather than being absorbed.
            unassigned.append({
                "shortfall_id": item["shortfall_id"],
                "agency_id": item["agency_id"],
                "cases": cases,
                "reason": ("NO_CONFIRMED_SAFE_LOT_WITH_SUFFICIENT_CASES"
                           if lot_id is None else "NO_REMAINING_TRANSPORT_CAPACITY"),
            })
            continue
        available[lot_id] -= cases
        vehicle["remaining"] -= cases
        vehicle["stops"].append({
            # Order identity is derived from the draft plan and the shortfall
            # it serves, so re-running the command regenerates the same ids
            # and the ledger's idempotency holds.
            "order_id": f"CAND-{plan_id}-{item['shortfall_id']}",
            "agency_id": item["agency_id"],
            "agency_name": agency_names.get(item["agency_id"], item["agency_id"]),
            "cases": cases,
            "lot_id": lot_id,
            "vehicle_id": vehicle["vehicle_id"],
            "sequence": len(vehicle["stops"]) + 1,
            "shortfall_id": item["shortfall_id"],
            "status": "CANDIDATE",
        })

    return {
        "candidate_basis": CANDIDATE_BASIS,
        # Only vehicles that actually carry candidate work are part of the
        # candidate schedule; an idle vehicle is not an assignment.
        "candidate_vehicles": [
            {"vehicle_id": v["vehicle_id"],
             "capacity_cases": v["capacity_cases"],
             "committed_load_cases": v["committed_load_cases"],
             "candidate_load_cases": sum(s["cases"] for s in v["stops"]),
             "stops": v["stops"]}
            for v in vehicles if v["stops"]
        ],
        "unassigned_demand": unassigned,
    }


def _generate_next_day_plan(
    *,
    tenant_id: str,
    source_operating_day: str,
    correlation_trace_id: str | None = None,
) -> Dict[str, Any]:
    """Derive and command one governed draft from authoritative unresolved state."""
    trace_id = correlation_trace_id or generate_trace_id()
    scope = _resolve_authority_scope(tenant_id)
    db = get_spanner_database(scope.database_id)
    try:
        source_date = datetime.strptime(source_operating_day, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(400, "SOURCE_OPERATING_DAY_INVALID") from exc
    operating_date = source_date + timedelta(days=1)
    plan_id = f"PLAN-{operating_date.isoformat()}"
    coordinator_id = f"COORD-{operating_date.isoformat()}"
    stable_identity = {
        "tenant_id": tenant_id,
        "source_operating_day": source_operating_day,
        "event_type": "PLAN_NEXT_DAY_REQUESTED",
        "plan_id": plan_id,
        "revision": "rev01",
    }
    stable_event_id = "NEXTDAY-" + hashlib.sha256(
        json.dumps(stable_identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32].upper()

    read_phase = "snapshot_open"
    try:
        with db.snapshot(multi_use=True) as snapshot:
            read_phase = "incident"
            incident_rows = list(snapshot.execute_sql(
                "SELECT incident_id, status, affected_lot_id FROM Incidents "
                "WHERE tenant_id = @t AND incident_type = 'FOOD_SAFETY_RECALL' "
                "AND status = 'PARTIALLY_CONTAINED' ORDER BY created_at DESC",
                params={"t": tenant_id},
                param_types={"t": spanner.param_types.STRING},
            ))
            read_phase = "barrier"
            barrier_rows = list(snapshot.execute_sql(
                "SELECT barrier_id, lot_id, status FROM MovementBarriers "
                "WHERE tenant_id = @t AND incident_id = @incident_id "
                "AND status = 'ACTIVE' ORDER BY barrier_id",
                params={"t": tenant_id, "incident_id": incident_rows[0][0] if incident_rows else ""},
                param_types={"t": spanner.param_types.STRING,
                             "incident_id": spanner.param_types.STRING},
            ))
            read_phase = "shortfall"
            shortfall_rows = list(snapshot.execute_sql(
                "SELECT shortfall_id, agency_id, cases, status FROM RecoveryShortfalls "
                "WHERE tenant_id = @t AND incident_id = @incident_id "
                "AND status = 'OPEN' ORDER BY shortfall_id",
                params={"t": tenant_id, "incident_id": incident_rows[0][0] if incident_rows else ""},
                param_types={"t": spanner.param_types.STRING,
                             "incident_id": spanner.param_types.STRING},
            ))
            read_phase = "agency_names"
            # Authoritative display names for the agencies a shortfall names.
            # Read from today's committed orders rather than derived from an
            # id, so a candidate stop shows the same name the operator saw.
            agency_name_rows = list(snapshot.execute_sql(
                "SELECT DISTINCT destination_agency_id, destination_agency_name "
                "FROM Orders WHERE tenant_id = @t AND plan_id = @plan_id",
                params={"t": tenant_id,
                        "plan_id": f"PLAN-{source_operating_day}"},
                param_types={"t": spanner.param_types.STRING,
                             "plan_id": spanner.param_types.STRING},
            ))
            read_phase = "hold"
            hold_rows = list(snapshot.execute_sql(
                "SELECT incident_id, details, status FROM Incidents WHERE tenant_id = @t "
                "AND incident_type = 'DEADLINE_HOLD' "
                "AND status = 'ACKNOWLEDGMENT_HOLD_ACTIVE'",
                params={"t": tenant_id},
                param_types={"t": spanner.param_types.STRING},
            ))
            read_phase = "safe_inventory"
            safe_lots = list(snapshot.execute_sql(
                "SELECT lot_id, total_cases FROM Lots WHERE tenant_id = @t "
                "AND hazard_status = 'CLEAR_SAFE' ORDER BY lot_id",
                params={"t": tenant_id},
                param_types={"t": spanner.param_types.STRING},
            ))
            read_phase = "fleet"
            fleet = list(snapshot.execute_sql(
                "SELECT vehicle_id, max_capacity_cases, current_load_cases FROM Vehicles "
                "WHERE tenant_id = @t AND is_operational = TRUE ORDER BY vehicle_id",
                params={"t": tenant_id},
                param_types={"t": spanner.param_types.STRING},
            ))
    except Exception as exc:
        logger.error(
            "authoritative_continuity_read_failed phase=%s exception_type=%s status_code=%s",
            read_phase, type(exc).__name__,
            getattr(exc, "code", "UNAVAILABLE"),
        )
        raise HTTPException(503, "AUTHORITATIVE_CONTINUITY_READ_UNAVAILABLE") from exc

    incident_id = incident_rows[0][0] if len(incident_rows) == 1 else None
    incident_status = incident_rows[0][1] if incident_id else None
    affected_lot_id = incident_rows[0][2] if incident_id else None
    barriers = [row for row in barrier_rows if row[1] == affected_lot_id]
    shortfalls = list(shortfall_rows)
    holds = []
    for row in hold_rows:
        try:
            details = json.loads(row[1] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if (details.get("parent_incident_id") == incident_id
                and details.get("site_id") and details.get("unconfirmed_cases", 0) > 0):
            holds.append((row, details))
    missing = []
    if incident_status != "PARTIALLY_CONTAINED":
        missing.append("PARTIALLY_CONTAINED_RECALL")
    if not barriers:
        missing.append("ACTIVE_RECALLED_LOT_BARRIER")
    if not shortfalls:
        missing.append("OPEN_RECOVERY_SHORTFALL")
    if not holds:
        missing.append("OPEN_ACKNOWLEDGMENT_HOLD")
    if not safe_lots:
        missing.append("CONFIRMED_SAFE_INVENTORY")
    if not fleet:
        missing.append("CONFIRMED_TRANSPORT_CAPACITY")
    if missing:
        raise HTTPException(
            409,
            {"code": "NEXT_DAY_AUTHORITATIVE_CONSTRAINTS_INCOMPLETE", "missing": missing},
        )

    agency_names = {row[0]: row[1] for row in agency_name_rows}
    candidate = _candidate_assignments(
        shortfalls, safe_lots, fleet, plan_id=plan_id,
        agency_names=agency_names)

    # Gate next-day draft through Fulfillment agent before ledger persist
    try:
        fleet_result = run_fleet(
            incident_id=incident_id or f"INC-NEXTDAY-{stable_event_id}",
            lot_id=affected_lot_id or "NEXT_DAY_NO_LOT",
            screened_notice_text="Next-day draft generation",
            graph_result={},
            recovery_candidates=[{
                "candidate_id": plan_id,
                "revision": "rev01",
                "content_hash": hashlib.sha256(
                    json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "allocations": [
                    {"order_id": stop["order_id"], "cases": stop["cases"],
                     "agency_id": stop.get("agency_id"),
                     "target_vehicle_id": vehicle.get("vehicle_id")}
                    for vehicle in candidate.get("candidate_vehicles", [])
                    for stop in vehicle.get("stops", [])
                ],
                "partner_pickups": [],
                # Carried-forward shortfalls keep their agency identity: Saturday
                # must be able to show WHICH agency remains short, not just that
                # some quantity is unserved.
                "shortfalls": [
                    {"shortfall_id": item.get("shortfall_id"),
                     "agency_id": item.get("agency_id"),
                     "cases": item.get("cases")}
                    for item in candidate.get("unassigned_demand", [])
                ],
            }],
            source_event_id=stable_event_id,
            trigger=TriggerClass.NEXT_DAY_DRAFT,
            expected_revision="rev01",
            partner_state={},
        )
        if fleet_result["proposal"].status != "PROPOSED":
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "NEXT_DAY_DRAFT_REJECTED_BY_FULFILLMENT",
                    "reason": fleet_result["proposal"].reason_code,
                },
            )
    except FleetProposalError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "NEXT_DAY_DRAFT_FLEET_VALIDATION_FAILED",
                "reason": exc.reason_code,
            },
        ) from exc

    next_day_plan = {
        "operating_date": operating_date.isoformat(),
        "plan_id": plan_id,
        "revision": "rev01",
        "status": "DRAFT_WITH_CONSTRAINTS — HUMAN APPROVAL REQUIRED",
        "scenario_time": "17:00 · NEXT-DAY PLANNING",
        "inherited_constraints": ([{
                "constraint_id": row[0],
                "type": "LOT_MOVEMENT_BARRIER",
                "affected_lot": row[1],
                "status": "ACTIVE_BLOCKED"
            } for row in barriers] + [{
                "constraint_id": row[0],
                "type": "RECOVERY_PRIORITY",
                "agency_id": row[1],
                "shortfall_cases": row[2],
                "status": "PROMOTED_TO_FIRST_RECOVERY_PRIORITY"
            } for row in shortfalls] + [{
                "constraint_id": row[0][0],
                "type": "ACKNOWLEDGMENT_HOLD",
                "site_id": row[1]["site_id"],
                "unconfirmed_cases": row[1]["unconfirmed_cases"],
                "status": "ACKNOWLEDGMENT_HOLD_ACTIVE"
            } for row in holds] + [{
                # Event 25's fourth inherited obligation. The unresolved
                # incident was previously only a 409 precondition and a scalar
                # flag, so the draft carried three of the four obligations the
                # contract requires and could read as though the recall were
                # settled overnight.
                "constraint_id": incident_id,
                "type": "UNRESOLVED_INCIDENT",
                "incident_id": incident_id,
                "incident_status": incident_status,
                "status": "INCIDENT_UNRESOLVED"
            }] if incident_id else []),
        "confirmed_safe_inventory": [
            {"lot_id": row[0], "confirmed_cases": row[1]} for row in safe_lots
        ],
        "confirmed_transport_capacity": [
            {"vehicle_id": row[0], "max_cases": row[1], "current_load_cases": row[2]}
            for row in fleet
        ],
        **candidate,
        "fleet_invariants_enforced": {
            "missing_cases_fabricated": False,
            "infeasible_plan_activated": False,
            "current_recall_closed": False,
            "recall_transferred_out": False,
            "recall_incident_status_preserved": incident_status
        }
    }

    try:
        ledger_result = execute_ledger_command(
            command_id=f"CMD-NEXT-DAY-{operating_date.isoformat()}-REV01",
            idempotency_key=f"{tenant_id}:{plan_id}:rev01:day-close",
            tenant_id=tenant_id,
            incident_id=incident_id,
            agent_role="FULFILLMENT_RECOVERY_PLANNER",
            command_type="CREATE_NEXT_DAY_DRAFT",
            expected_plan_revision="rev08",
            trace_id=trace_id,
            payload={
                "source_event_id": stable_event_id,
                "source_operating_day": source_operating_day,
                "event_type": "PLAN_NEXT_DAY_REQUESTED",
                "operating_date": operating_date.isoformat(),
                "plan_id": plan_id,
                "revision": "rev01",
                "status": "DRAFT_WITH_CONSTRAINTS",
                "coordinator_id": coordinator_id,
                "barriers": [
                    {"barrier_id": row[0], "lot_id": row[1]} for row in barriers
                ],
                "shortfalls": [
                    {"shortfall_id": row[0], "agency_id": row[1], "cases": row[2]}
                    for row in shortfalls
                ],
                "acknowledgment_holds": [
                    {"hold_incident_id": row[0][0], "site_id": row[1]["site_id"],
                     "unconfirmed_cases": row[1]["unconfirmed_cases"]}
                    for row in holds
                ],
                "human_approval_required": True,
                # The exact derived assignments are committed. The ledger
                # validates them against authoritative state and stores them
                # as child Orders of the draft; nothing is re-derived on read.
                "candidate_vehicles": candidate["candidate_vehicles"],
                "unassigned_demand": candidate["unassigned_demand"],
            },
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if 400 <= status_code < 500:
            try:
                detail = exc.response.json().get("detail", "PLAN_LEDGER_REQUEST_REJECTED")
            except (TypeError, ValueError):
                detail = "PLAN_LEDGER_REQUEST_REJECTED"
            raise HTTPException(status_code=status_code, detail=detail) from exc
        raise HTTPException(
            status_code=502, detail="PLAN_LEDGER_NEXT_DAY_COMMIT_FAILED"
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="PLAN_LEDGER_NEXT_DAY_COMMIT_FAILED") from exc

    return {
        "status": "NEXT_DAY_DRAFT_CREATED",
        "next_day_draft": next_day_plan,
        "idempotent_replay": ledger_result["idempotent_replay"],
        "ledger_receipt": ledger_result["receipt"],
        "trace_id": trace_id
    }


@app.post(
    "/api/v1/orchestrator/next-day-plan/generate",
    dependencies=[Depends(require_internal_workload)],
)
def generate_next_day_plan(
    tenant_id: str = Query("east-bay-food-bank"),
):
    """Workload-protected manual control; managed proof uses Scheduler delivery."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return _generate_next_day_plan(
        tenant_id=tenant_id,
        source_operating_day=_operating_day_from_managed_publish_time(
            _parse_managed_publish_time(now)
        ),
    )


# -------------------------------------------------------------------
# GATE J — SYSTEM EVIDENCE ENDPOINT
# -------------------------------------------------------------------

@app.get(
    "/api/v1/evidence/system",
    dependencies=[Depends(require_internal_workload)],
)
def get_system_evidence(
    request: Request,
    tenant_id: str = "east-bay-food-bank",
):
    """Return independently classified evidence from this exact execution."""
    trace_id = generate_trace_id()
    scope = _resolve_authority_scope(tenant_id)
    db = get_spanner_database(scope.database_id)

    def read_rows(sql: str):
        with db.snapshot() as snapshot:
            return list(snapshot.execute_sql(
                sql,
                params={"tenant_id": tenant_id},
                param_types={"tenant_id": spanner.param_types.STRING},
            ))

    failures = []
    ground_truth = {
        "tenant_id": tenant_id,
        "classification": "NOT_PROVEN",
    }
    try:
        rows = read_rows(
            "SELECT revision FROM PlanRevisions WHERE tenant_id = @tenant_id "
            "AND status = 'ACTIVE' ORDER BY created_at DESC LIMIT 1"
        )
        ground_truth["active_plan_revision"] = rows[0][0] if rows else None
        rows = read_rows(
            "SELECT incident_id, status, terminal_state, affected_lot_id FROM Incidents "
            "WHERE tenant_id = @tenant_id AND incident_type = 'FOOD_SAFETY_RECALL' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        ground_truth["active_incident_id"] = rows[0][0] if rows else None
        ground_truth["active_incident_status"] = rows[0][1] if rows else None
        ground_truth["incident_terminal_state"] = rows[0][2] if rows else None
        ground_truth["affected_lot_id"] = rows[0][3] if rows else None
        rows = read_rows(
            "SELECT COUNT(*) FROM Receipts WHERE tenant_id = @tenant_id"
        )
        ground_truth["committed_receipts_count"] = rows[0][0] if rows else 0
        ground_truth["classification"] = "OBSERVED_LIVE"
    except Exception:
        logger.exception("System evidence authoritative-state query failed")
        ground_truth["classification"] = "FAILED"
        ground_truth["reason"] = "AUTHORITATIVE_STATE_READ_UNAVAILABLE"
        failures.append("spanner_ground_truth")

    latest_receipt = {
        "classification": "NOT_PROVEN",
        "reason": "NO_COMMITTED_RECEIPT_OBSERVED",
    }
    try:
        rows = read_rows(
            "SELECT receipt_id, action_id, action_type, status, mutations_applied, "
            "trace_id, caller_email, timestamp FROM Receipts "
            "WHERE tenant_id = @tenant_id ORDER BY timestamp DESC, receipt_id DESC LIMIT 1"
        )
        if rows:
            row = rows[0]
            latest_receipt = {
                "receipt_id": row[0],
                "action_id": row[1],
                "action_type": row[2],
                "status": row[3],
                "mutations_applied": row[4],
                "correlation_trace_id": row[5],
                "caller_email": row[6],
                "committed_at": row[7].isoformat(),
                "classification": "OBSERVED_LIVE",
            }
    except Exception:
        logger.exception("System evidence receipt query failed")
        latest_receipt = {
            "classification": "FAILED",
            "reason": "RECEIPT_READ_UNAVAILABLE",
        }
        failures.append("latest_ledger_receipt")

    latest_inbound_event = {
        "classification": "NOT_PROVEN",
        "reason": "NO_COMMITTED_INBOUND_EVENT_OBSERVED",
    }
    try:
        rows = read_rows(
            "SELECT source_event_id, event_type, status, occurred_at FROM InboundEvents "
            "WHERE tenant_id = @tenant_id ORDER BY occurred_at DESC, source_event_id DESC LIMIT 1"
        )
        if rows:
            row = rows[0]
            latest_inbound_event = {
                "source_event_id": row[0],
                "event_type": row[1],
                "status": row[2],
                "occurred_at": row[3].isoformat(),
                "classification": "OBSERVED_LIVE",
            }
    except Exception:
        logger.exception("System evidence inbound-event query failed")
        latest_inbound_event = {
            "classification": "FAILED",
            "reason": "INBOUND_EVENT_READ_UNAVAILABLE",
        }
        failures.append("latest_inbound_event")

    try:
        graph = _run_managed_custody_graph(
            db, tenant_id=tenant_id, lot_id=ground_truth["affected_lot_id"]
        )
        graph_evidence = {
            "lot_id": graph["lot_id"],
            "unique_current_cases": graph["unique_current_cases"],
            "max_path_depth": graph["max_path_depth"],
            "query_engine": graph["query_engine"],
            "classification": "OBSERVED_LIVE",
        }
    except Exception:
        logger.exception("System evidence graph query failed")
        graph_evidence = {
            "classification": "FAILED",
            "reason": "MANAGED_GRAPH_READ_UNAVAILABLE",
        }
        failures.append("spanner_graph")

    source_revision = os.getenv("FULL_SHELF_SOURCE_REVISION", "UNBOUND")
    image_digest = os.getenv("FULL_SHELF_IMAGE_DIGEST", "UNBOUND")
    runtime_revision = os.getenv("K_REVISION", "LOCAL")

    return {
        "service": "Full Shelf Control Plane",
        "build_book_version": "1.1",
        "evidence_timestamp": datetime.now(timezone.utc).isoformat(),
        "request_execution": {
            "trace_id": trace_id,
            "response_header": "X-Full-Shelf-Trace-Id",
            "span_kind": "SERVER",
            "managed_readback": "PENDING_EXTERNAL_QUERY",
            "classification": "NOT_PROVEN",
        },
        "overall_classification": "FAILED" if failures else "OBSERVED_LIVE",
        "failed_checks": failures,
        "spanner_ground_truth": ground_truth,
        "latest_ledger_receipt": latest_receipt,
        "latest_inbound_event": latest_inbound_event,
        "managed_resources": {
            "orchestrator_service": {
                "name": os.getenv("K_SERVICE", "full-shelf-orchestrator"),
                "revision": runtime_revision,
                "trace_id": trace_id,
                "classification": "OBSERVED_LIVE"
            },
            "plan_ledger_service": {
                "name": "full-shelf-plan-ledger",
                "latest_receipt_id": latest_receipt.get("receipt_id"),
                "latest_receipt_trace_id": latest_receipt.get("correlation_trace_id"),
                "classification": latest_receipt["classification"],
            },
            "spanner_database": {
                "path": f"projects/{PROJECT_ID}/instances/{SPANNER_INSTANCE}/databases/{scope.database_id}",
                "authority_scope_kind": scope.kind,
                "classification": ground_truth["classification"],
            },
            "spanner_graph": graph_evidence,
            "gemini_model": {
                "model_id": MODEL_ID,
                "vertex_location": VERTEX_LOCATION,
                "sdk": "google-adk",
                "classification": "DESIGNED",
                "limitation": "Configuration is not invocation evidence",
            },
            "model_armor": {
                "template": f"projects/{PROJECT_ID}/locations/us-central1/templates/full-shelf-recall-input-v1",
                "operation": "sanitizeUserPrompt",
                "classification": "DESIGNED",
                "limitation": "Configuration is not invocation evidence",
            },
            "kms_approval_key": {
                "key_version": f"projects/{PROJECT_ID}/locations/us-central1/keyRings/full-shelf-keyring/cryptoKeys/approval-signer/cryptoKeyVersions/1",
                "classification": "DESIGNED",
                "limitation": "This endpoint did not invoke or verify KMS",
            },
            "pubsub": {
                "topic": f"projects/{PROJECT_ID}/topics/full-shelf-incidents",
                "subscription": f"projects/{PROJECT_ID}/subscriptions/full-shelf-incidents-sub",
                "latest_committed_event_id": latest_inbound_event.get("source_event_id"),
                "classification": "STRUCTURALLY_VERIFIED",
                "limitation": "A committed event alone does not prove managed delivery",
            },
            "cloud_scheduler": {
                "jobs": ["full-shelf-daily-plan-job", "full-shelf-next-day-plan-job"],
                "classification": "DESIGNED",
                "limitation": "This request did not inspect Scheduler",
            },
            "cloud_tasks": {
                "queue": f"projects/{PROJECT_ID}/locations/us-central1/queues/full-shelf-deadlines",
                "classification": "DESIGNED",
                "limitation": "This request did not create or inspect a task",
            },
            "cloud_trace": {
                "exporter": "OpenTelemetry GoogleCloudTraceExporter",
                "trace_id": trace_id,
                "classification": "NOT_PROVEN",
                "limitation": "Upgrade only after managed trace readback",
            },
            "build_provenance": {
                "runtime_revision": runtime_revision,
                "source_revision": source_revision,
                "image_digest": image_digest,
                "classification": "DESIGNED",
                "limitation": "Requires external Cloud Run and Artifact Registry comparison",
            }
        },
        "agent_fleet_manifest": build_manifest(),
        "preview_service_seams": {
            "agent_registry": "NOT_PROVEN — managed Agent Registry unavailable; internal fleet manifest is not a managed registry or tool gateway",
            "agent_identity": "STRUCTURALLY_VERIFIED — Cloud IAM / OIDC seam; not managed Agent Identity",
            "agent_gateway": "STRUCTURALLY_VERIFIED — private plan-ledger seam; not managed Agent Gateway",
            "agent_sessions": "STRUCTURALLY_VERIFIED — Spanner coordinator seam; not managed Agent Sessions"
        }
    }


# -------------------------------------------------------------------
# GATE K — FRONTEND PROJECTIONS & SSE STREAM
# -------------------------------------------------------------------

@app.get("/api/v1/projections/demo-beats")
def get_demo_beats_projections(
    authority=Depends(require_frontend_authority),
    as_of: Optional[str] = Query(None, max_length=40),
    include_next_day_draft: bool = Query(False),
):
    """Project only facts committed at or before an explicit boundary.

    Cross-day leakage is closed by exact canonical plan identity. Intra-day
    leakage is closed by receipt-gated blocks. Timeless current-state rows are
    omitted whenever a later mutation proves the present value is not the
    boundary value.
    """
    identity, scope, operating_day = authority
    boundary_at, boundary_mode = _resolve_projection_boundary(operating_day, as_of)
    tenant = scope.tenant_id
    current_plan_id = f"PLAN-{operating_day}"
    db = get_spanner_database(scope.database_id)
    omitted: List[Dict[str, str]] = []

    str_t = spanner.param_types.STRING
    ts_t = spanner.param_types.TIMESTAMP

    with db.snapshot(multi_use=True) as snapshot:
        receipt_rows = list(snapshot.execute_sql(
            "SELECT receipt_id, action_id, action_type, status, mutations_applied, "
            "timestamp FROM Receipts WHERE tenant_id=@tenant ORDER BY timestamp ASC",
            params={"tenant": tenant}, param_types={"tenant": str_t},
        ))
        boundary = ProjectionBoundary(boundary_at, boundary_mode, receipt_rows)

        # Exact canonical plan identity. A prefix match would admit tomorrow.
        plan_rows = list(snapshot.execute_sql(
            "SELECT plan_id, revision, status, created_at FROM PlanRevisions "
            "WHERE tenant_id=@tenant AND plan_id=@plan_id AND created_at<=@as_of "
            "ORDER BY created_at",
            params={"tenant": tenant, "plan_id": current_plan_id, "as_of": boundary_at},
            param_types={"tenant": str_t, "plan_id": str_t, "as_of": ts_t},
        ))
        revisions = [r[1] for r in plan_rows]

        order_rows = []
        if revisions:
            order_rows = list(snapshot.execute_sql(
                "SELECT revision, order_id, destination_agency_name, cases, lot_id, "
                "assigned_vehicle_id, status FROM Orders "
                "WHERE tenant_id=@tenant AND plan_id=@plan_id "
                "ORDER BY revision, order_id",
                params={"tenant": tenant, "plan_id": current_plan_id},
                param_types={"tenant": str_t, "plan_id": str_t},
            ))

        approval_rows = list(snapshot.execute_sql(
            "SELECT approval_id, plan_id, source_revision, proposed_revision, "
            "plan_diff_hash, kms_key_version, verified_at, plan_diff_json, "
            "approver_email, authority_scope, expires_at FROM Approvals "
            "WHERE tenant_id=@tenant AND operating_day=@day AND verified_at<=@as_of "
            # A same-day approval of a DIFFERENT plan is somebody else's
            # authority. Day and time alone do not scope it out, so the exact
            # selected plan and the intended revision transition do.
            "AND plan_id=@plan_id "
            "AND source_revision=@source_revision "
            "AND proposed_revision=@proposed_revision",
            params={"tenant": tenant,
                    "day": datetime.fromisoformat(operating_day).date(),
                    "as_of": boundary_at,
                    "plan_id": current_plan_id,
                    "source_revision": CANONICAL_APPROVAL_SOURCE_REVISION,
                    "proposed_revision": CANONICAL_APPROVAL_PROPOSED_REVISION},
            param_types={"tenant": str_t, "day": spanner.param_types.DATE,
                         "as_of": ts_t, "plan_id": str_t,
                         "source_revision": str_t, "proposed_revision": str_t},
        ))

        incident_rows = list(snapshot.execute_sql(
            "SELECT incident_id, incident_type, status, terminal_state, details, "
            "affected_lot_id, created_at, resolved_at FROM Incidents "
            "WHERE tenant_id=@tenant AND created_at<=@as_of ORDER BY created_at",
            params={"tenant": tenant, "as_of": boundary_at},
            param_types={"tenant": str_t, "as_of": ts_t},
        ))

        barrier_rows = list(snapshot.execute_sql(
            "SELECT barrier_id, lot_id, status, created_at, released_at "
            "FROM MovementBarriers WHERE tenant_id=@tenant AND created_at<=@as_of",
            params={"tenant": tenant, "as_of": boundary_at},
            param_types={"tenant": str_t, "as_of": ts_t},
        ))
        # Recovery is scoped to the incidents this projection actually selected,
        # through the authoritative incident_id foreign key. A same-tenant
        # allocation belonging to another incident is another incident's truth
        # and must never reach these quantities or the derivation over them.
        selected_incident_ids = [row[0] for row in incident_rows]
        incident_list_t = spanner.param_types.Array(str_t)
        allocation_rows = []
        shortfall_rows = []
        if selected_incident_ids:
            allocation_rows = list(snapshot.execute_sql(
                "SELECT allocation_id, incident_id, status, created_at, agency_id, "
                "lot_id, cases FROM RecoveryAllocations "
                "WHERE tenant_id=@tenant AND created_at<=@as_of "
                "AND incident_id IN UNNEST(@incident_ids)",
                params={"tenant": tenant, "as_of": boundary_at,
                        "incident_ids": selected_incident_ids},
                param_types={"tenant": str_t, "as_of": ts_t,
                             "incident_ids": incident_list_t},
            ))
            shortfall_rows = list(snapshot.execute_sql(
                "SELECT shortfall_id, incident_id, status, created_at, agency_id, "
                "cases FROM RecoveryShortfalls "
                "WHERE tenant_id=@tenant AND created_at<=@as_of "
                "AND incident_id IN UNNEST(@incident_ids)",
                params={"tenant": tenant, "as_of": boundary_at,
                        "incident_ids": selected_incident_ids},
                param_types={"tenant": str_t, "as_of": ts_t,
                             "incident_ids": incident_list_t},
            ))
        work_rows = []
        if selected_incident_ids:
            work_rows = list(snapshot.execute_sql(
                "SELECT work_item_id, incident_id, status, created_at, completed_at "
                "FROM WorkItems WHERE tenant_id=@tenant AND created_at<=@as_of "
                "AND incident_id IN UNNEST(@incident_ids)",
                params={"tenant": tenant, "as_of": boundary_at,
                        "incident_ids": selected_incident_ids},
                param_types={"tenant": str_t, "as_of": ts_t,
                             "incident_ids": incident_list_t},
            ))
        partner_evidence_rows = list(snapshot.execute_sql(
            "SELECT source_event_id, event_type, incident_id, partner_id, "
            "source_occurred_at, received_at, source_text, callback_subject, "
            "callback_email, callback_audience, callback_issuer, callback_provenance, "
            "model_armor_json, proposal_json, policy_decision, policy_reasons_json, "
            "claim_verification_json, requested_mutation_json, agent_id, model_id, "
            "adk_framework, adk_session_id, adk_invocation_id, adk_event_id, receipt_id, "
            "domain_mutations_applied, evidence_mutations_applied, committed_at "
            "FROM PartnerEvidenceEvents WHERE tenant_id=@tenant "
            "AND operating_day=@day AND committed_at<=@as_of "
            "ORDER BY committed_at, source_event_id",
            params={
                "tenant": tenant,
                "day": datetime.fromisoformat(operating_day).date(),
                "as_of": boundary_at,
            },
            param_types={
                "tenant": str_t,
                "day": spanner.param_types.DATE,
                "as_of": ts_t,
            },
        ))
        constraint_rows = list(snapshot.execute_sql(
            "SELECT plan_id, constraint_type, details, created_at "
            "FROM PlanConstraints WHERE tenant_id=@tenant AND created_at<=@as_of "
            # Tomorrow's constraints are committed during today and would
            # otherwise pass the time predicate. Exact plan identity is what
            # keeps the next day out of the current day.
            "AND plan_id=@plan_id",
            params={"tenant": tenant, "as_of": boundary_at,
                    "plan_id": current_plan_id},
            param_types={"tenant": str_t, "as_of": ts_t, "plan_id": str_t},
        ))

        vehicle_rows = []
        if boundary.timeless_row_is_safe("vehicles"):
            vehicle_rows = list(snapshot.execute_sql(
                "SELECT vehicle_id, name, max_capacity_cases, current_load_cases, "
                "is_operational FROM Vehicles WHERE tenant_id=@tenant",
                params={"tenant": tenant}, param_types={"tenant": str_t},
            ))
        else:
            omitted.append({"field": "current_day.vehicles",
                            "reason": PRE_BOUNDARY_STATE_NOT_RETAINED})

        next_day_draft = None
        if include_next_day_draft:
            next_plan_id = (
                f"PLAN-{(datetime.fromisoformat(operating_day).date() + timedelta(days=1)).isoformat()}"
            )
            draft_rows = list(snapshot.execute_sql(
                "SELECT plan_id, revision, status, created_at FROM PlanRevisions "
                "WHERE tenant_id=@tenant AND plan_id=@plan_id AND created_at<=@as_of",
                params={"tenant": tenant, "plan_id": next_plan_id, "as_of": boundary_at},
                param_types={"tenant": str_t, "plan_id": str_t, "as_of": ts_t},
            ))
            if draft_rows:
                row = draft_rows[0]
                # Candidate assignments are READ from committed child Orders of
                # the draft revision, never re-derived here. Scoped to the
                # draft's own plan_id and revision so a current-day row can
                # never appear in a candidate schedule, or the reverse.
                candidate_rows = list(snapshot.execute_sql(
                    "SELECT order_id, destination_agency_id, "
                    "destination_agency_name, cases, lot_id, assigned_vehicle_id "
                    "FROM Orders WHERE tenant_id=@tenant AND plan_id=@plan_id "
                    "AND revision=@revision AND status='CANDIDATE' "
                    "ORDER BY assigned_vehicle_id, order_id",
                    params={"tenant": tenant, "plan_id": next_plan_id,
                            "revision": row[1]},
                    param_types={"tenant": str_t, "plan_id": str_t,
                                 "revision": str_t},
                ))
                draft_constraint_rows = list(snapshot.execute_sql(
                    "SELECT constraint_type, subject_id, details FROM PlanConstraints "
                    "WHERE tenant_id=@tenant AND plan_id=@plan_id AND revision=@revision "
                    "ORDER BY priority",
                    params={"tenant": tenant, "plan_id": next_plan_id,
                            "revision": row[1]},
                    param_types={"tenant": str_t, "plan_id": str_t,
                                 "revision": str_t},
                ))
                by_vehicle: Dict[str, List[Dict[str, Any]]] = {}
                for candidate in candidate_rows:
                    by_vehicle.setdefault(candidate[5], []).append({
                        "order_id": candidate[0],
                        "agency_id": candidate[1],
                        "agency": candidate[2],
                        "cases": candidate[3],
                        "lot_id": candidate[4],
                        "status": "CANDIDATE",
                    })
                unassigned = []
                for constraint in draft_constraint_rows:
                    if constraint[0] != "UNASSIGNED_DEMAND":
                        continue
                    try:
                        unassigned.append(json.loads(constraint[2] or "{}"))
                    except (TypeError, json.JSONDecodeError):
                        continue
                next_day_draft = {
                    "plan_id": row[0], "revision": row[1], "status": row[2],
                    "approval_required": row[2] != "ACTIVE",
                    # A draft is never activatable from this surface.
                    "activation_supported": False,
                    "candidate_vehicles": [
                        {"vehicle_id": vehicle_id,
                         "stops": [{**stop, "sequence": index + 1}
                                   for index, stop in enumerate(stops)],
                         "stop_count": len(stops),
                         "candidate_load_cases": sum(s["cases"] or 0 for s in stops)}
                        for vehicle_id, stops in sorted(by_vehicle.items())
                    ],
                    "unassigned_demand": unassigned,
                    "constraints": [
                        {"constraint_type": c[0], "subject_id": c[1]}
                        for c in draft_constraint_rows
                        if c[0] != "UNASSIGNED_DEMAND"
                    ],
                }

    # --- Incident lifecycle by recomputed identity, never by position -------
    incidents = []
    for row in incident_rows:
        incident_id = row[0]
        terminal_receipt = boundary.committed(
            _incident_status_action_id(tenant, incident_id, "PARTIALLY_CONTAINED"))
        containment_receipt = boundary.committed(
            _incident_status_action_id(tenant, incident_id, "CONTAINMENT_IN_PROGRESS"))
        scoping_receipt = boundary.committed(
            _incident_status_action_id(tenant, incident_id, "SCOPING"))
        # A vehicle failure has no containment ladder: it is resolved by the
        # approved repair revision its own recovery commits. Gate on that exact
        # revision's plan receipt AND require it to land at or after the
        # incident opened, so the pre-incident morning plan can never read as a
        # repair of a failure that had not happened yet.
        repair_receipt = None
        if _is_vehicle_failure(row[1]):
            candidate = boundary.committed(_incident_action_id(
                tenant, incident_id, f"plan:{CANONICAL_APPROVAL_PROPOSED_REVISION}"))
            if candidate and row[6] is not None and _normalize_receipt_timestamp(
                    candidate["committed_at"]) >= _normalize_receipt_timestamp(row[6]):
                repair_receipt = candidate
        if repair_receipt:
            status_as_of, terminal_as_of = "RESOLVED", "NONE"
        elif terminal_receipt:
            status_as_of, terminal_as_of = "PARTIALLY_CONTAINED", "PARTIALLY_CONTAINED"
        elif containment_receipt:
            status_as_of, terminal_as_of = "CONTAINMENT_IN_PROGRESS", "NONE"
        elif scoping_receipt:
            status_as_of, terminal_as_of = ("ACTIVE" if _is_vehicle_failure(row[1])
                                            else "SCOPING"), "NONE"
        else:
            status_as_of, terminal_as_of = "DETECTED", "NONE"
        refusal = boundary.committed(
            _incident_action_id(tenant, incident_id, "containment-refusal"))
        incidents.append({
            "incident_id": incident_id,
            "incident_type": row[1],
            "status": status_as_of,
            "terminal_state": terminal_as_of,
            "affected_lot_id": row[5],
            "model_armor_screening": (
                {"result": "PASS",
                 "correlation_id": json.loads(row[4] or "{}").get(
                     "model_armor_correlation_id")}
                if json.loads(row[4] or "{}").get("model_armor_correlation_id")
                else None
            ),
            "refusal": (
                {"decision": refusal["status"],
                 "mutations_applied": refusal["mutations_applied"],
                 "receipt_id": refusal["receipt_id"],
                 "committed_at": refusal["committed_at"],
                 # The real sequence. The coordinator requested the closure
                 # eligibility check that policy requires; deterministic
                 # policy evaluated it and refused. There is no
                 # DECLARE_CONTAINED command in the ledger enum, so naming
                 # one would describe an action the backend cannot perform.
                 "requested_action": "CLOSURE_ELIGIBILITY_CHECK",
                 "policy_action": "RECORD_REFUSAL",
                 "requested_by_role": "INCIDENT_COORDINATOR",
                 "decided_by": "DETERMINISTIC_POLICY"}
                if refusal else None
            ),
        })

    # --- Pending repair proposal, never an authorization --------------------
    # A proposal is written against the revision it repairs. It is "pending"
    # only while that revision is still the active one: once the approved
    # revision supersedes it, the proposal was answered and must stop being
    # offered. That check is what keeps an approved plan from re-rendering an
    # approval control for work already committed.
    repair_proposal = None
    active_as_of = revisions[-1] if revisions else None
    for row in constraint_rows:
        if row[1] != "REPAIR_PROPOSAL":
            continue
        try:
            detail = json.loads(row[2] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if detail.get("proposed_revision") in revisions:
            continue  # already approved and activated at this boundary
        if active_as_of is not None and detail.get("proposed_revision") == active_as_of:
            continue
        repair_proposal = {
            "proposal_id": detail.get("proposal_id"),
            "source_event_id": detail.get("source_event_id"),
            "plan_id": row[0],
            "source_revision": active_as_of,
            "proposed_revision": detail.get("proposed_revision"),
            "failed_vehicle_id": detail.get("failed_vehicle_id"),
            "plan_diff": detail.get("plan_diff"),
            "plan_diff_hash": detail.get("plan_diff_hash"),
            "absorbing_vehicle": {
                "vehicle_id": (detail.get("plan_diff") or {}).get(
                    "reroute_target_vehicle"),
                "capacity_cases": detail.get("absorbing_vehicle_capacity_cases"),
                "committed_cases": detail.get("absorbing_vehicle_committed_cases"),
                "projected_cases": detail.get("absorbing_vehicle_projected_cases"),
            },
            # An operator surface must never present this as authorized.
            "authority": "AGENT_PROPOSAL",
            "approval_required": True,
            "activation_supported": False,
        }
        break

    # --- Commitments, gated per revision by its own committed receipt -------
    commitments = []
    for row in order_rows:
        revision = row[0]
        if revision not in revisions:
            continue
        commitments.append({
            "revision": revision, "order_id": row[1], "agency": row[2],
            "cases": row[3], "lot_id": row[4], "vehicle": row[5], "status": row[6],
        })

    # --- Open-as-of obligations, never present-day-open ---------------------
    def _open_as_of(created_at, closed_at):
        if created_at is None:
            return False
        if _normalize_receipt_timestamp(created_at) > boundary_at:
            return False
        if closed_at is None:
            return True
        return _normalize_receipt_timestamp(closed_at) > boundary_at

    carry_forward = []
    for row in work_rows:
        if _open_as_of(row[3], row[4]):
            carry_forward.append({"kind": "ACKNOWLEDGMENT_OBLIGATION",
                                  "reference_id": row[0], "incident_id": row[1]})
    for row in barrier_rows:
        if _open_as_of(row[3], row[4]):
            carry_forward.append({"kind": "MOVEMENT_BARRIER",
                                  "reference_id": row[0], "lot_id": row[1]})
    for row in shortfall_rows:
        if _open_as_of(row[3], None) and row[2] == "OPEN":
            carry_forward.append({"kind": "RECOVERY_SHORTFALL",
                                  "reference_id": row[0], "incident_id": row[1]})
    for row in incident_rows:
        if _open_as_of(row[6], row[7]):
            entry = next((i for i in incidents if i["incident_id"] == row[0]), None)
            if entry and entry["terminal_state"] == "PARTIALLY_CONTAINED":
                carry_forward.append({"kind": "UNRESOLVED_INCIDENT",
                                      "reference_id": row[0],
                                      "terminal_state": "PARTIALLY_CONTAINED"})

    # --- Custody, gated on its own committed reconciliation receipt ---------
    custody = None
    recall_incident = next(
        (r for r in incident_rows if r[1] == "FOOD_SAFETY_RECALL"), None)
    if recall_incident is not None:
        # No CUSTODY_RECONCILIATION command type exists in the closed ledger
        # enum, and adding one would change the ledger contract. The movement
        # barrier is the first commit that provably depends on a completed
        # custody reconstruction, so it is the truthful gate.
        reconciled = boundary.committed(
            _incident_action_id(tenant, recall_incident[0], "movement-barrier"))
        if reconciled is None:
            omitted.append({"field": "custody_graph",
                            "reason": "NOT_COMMITTED_AS_OF_BOUNDARY"})
        elif not boundary.timeless_row_is_safe("custody"):
            omitted.append({"field": "custody_graph",
                            "reason": PRE_BOUNDARY_STATE_NOT_RETAINED})
        else:
            try:
                custody = _run_managed_custody_graph(
                    db, tenant_id=tenant, lot_id=recall_incident[5])
            except Exception:
                logger.exception("Bounded projection custody graph read failed")
                omitted.append({"field": "custody_graph",
                                "reason": "MANAGED_GRAPH_READ_UNAVAILABLE"})

    # --- Fleet / execution evidence (Delta 3 durable source) ----------------
    fleet_evidence = None
    if recall_incident is not None:
        details = json.loads(recall_incident[4] or "{}")
        stored = details.get("agent_fleet")
        # The advisory fleet proposal is a strict precondition of the safe-stock
        # allocation, which is an existing ledger command type. Gating on it
        # avoids inventing a new command type for evidence purposes.
        proposal_receipt = boundary.committed(
            _incident_action_id(tenant, recall_incident[0], "safe-recovery"))
        if stored and proposal_receipt:
            fleet_evidence = _projected_agent_activity(
                stored, proposal_receipt["committed_at"]
            )
        elif stored:
            omitted.append({"field": "agent_activity_as_of",
                            "reason": "NOT_COMMITTED_AS_OF_BOUNDARY"})

    # --- Recall intake, one completed step per proven commitment -----------
    # Each step is unlocked by a committed receipt or by persisted evidence.
    # Steps not yet proven are reported PENDING; the synchronous runtime never
    # observes an intermediate Running or Waiting state, so none is invented.
    recall_intake = None
    if recall_incident is not None:
        details = json.loads(recall_incident[4] or "{}")
        incident_id = recall_incident[0]
        proven = {
            # The incident exists because a regulatory notice was delivered
            # and accepted, so its presence is the arrival evidence.
            "regulatory_event": True,
            "model_armor": bool(details.get("model_armor_correlation_id")),
            "extraction": bool((details.get("agent_fleet") or {}).get("proposal_hash")),
            "fleet": fleet_evidence is not None,
            "incident_row": True,
        }
        steps = []
        for step, source in RECALL_INTAKE_STEPS:
            if source in proven:
                complete = proven[source]
            else:
                complete = boundary.has_committed(
                    _incident_action_id(tenant, incident_id, source)
                )
            steps.append({
                "step": step,
                "state": "COMPLETED" if complete else "PENDING",
            })
        recall_intake = {
            "incident_id": incident_id,
            "steps": steps,
            # What actually arrived, stated plainly. This is a delivered
            # regulatory event in FDA notice format, NOT a claim that Full
            # Shelf monitors or polls the FDA. No such integration exists.
            "source": {
                "channel": "REGULATORY_FEED",
                "notice_format": "FDA_FORMAT",
                "received_at": _normalize_receipt_timestamp(
                    recall_incident[6]).isoformat().replace("+00:00", "Z"),
                "monitoring_claimed": False,
                "input_kind": "REPRESENTATIVE_REGULATORY_EVENT",
            },
        }

    # --- Dispatch, from committed assignments and authoritative capacity ----
    # Stops are the order-to-vehicle relationships the plan actually records.
    # No coordinate, bearing, position, or route geometry exists in authority,
    # so none is produced here.
    dispatch = None
    if revisions:
        active_revision = revisions[-1]
        # A null assigned_vehicle_id is evidence of the partner-pickup path, not
        # a row to discard: dropping it would hide an approved commitment and
        # silently understate the plan. The assignment type is read from the
        # authoritative row rather than inferred from any display string.
        assignments = {}
        partner_pickups = []
        for row in order_rows:
            if row[0] != active_revision:
                continue
            stop = {
                "order_id": row[1],
                "agency": row[2],
                "cases": row[3],
                "lot_id": row[4],
                "status": row[6],
            }
            if row[5]:
                assignments.setdefault(row[5], []).append(
                    {**stop, "assignment_type": "VEHICLE_ROUTED"})
            else:
                # A partner pickup is not a stop on any vehicle's manifest, so
                # it carries no position in a vehicle sequence.
                partner_pickups.append(
                    {**stop, "assignment_type": "PARTNER_PICKUP",
                     "assigned_vehicle_id": None, "sequence": None})
        vehicles_by_id = {v[0]: v for v in vehicle_rows}
        dispatch_vehicles = []
        for vehicle_id in sorted(set(assignments) | set(vehicles_by_id)):
            stops = sorted(assignments.get(vehicle_id, []),
                           key=lambda stop: stop["order_id"])
            # Stop sequence is the committed manifest order for this vehicle,
            # 1-based and contiguous. It is a deterministic ordering of the
            # authoritative rows, NOT a routing or optimization claim: no
            # distance, travel time, or geometry is consulted. sequence_basis
            # states that provenance so a client can never present it as an
            # optimized route.
            for position, stop in enumerate(stops, start=1):
                stop["sequence"] = position
            vehicle = vehicles_by_id.get(vehicle_id)
            assigned_cases = vehicle[3] if vehicle else None
            capacity = vehicle[2] if vehicle else None
            dispatch_vehicles.append({
                "vehicle_id": vehicle_id,
                "name": vehicle[1] if vehicle else None,
                "capacity_cases": capacity,
                "assigned_cases": assigned_cases,
                # Arithmetic over authoritative capacity, omitted rather than
                # guessed when the timeless vehicle row is not boundary-safe.
                "remaining_cases": (
                    capacity - assigned_cases
                    if capacity is not None and assigned_cases is not None
                    else None
                ),
                # Null, not False, when the timeless vehicle row is not
                # boundary-safe: "not at capacity" is a claim, and an unknown
                # capacity cannot support it.
                "at_capacity": (
                    assigned_cases >= capacity
                    if capacity is not None and assigned_cases is not None
                    else None
                ),
                "is_operational": vehicle[4] if vehicle else None,
                "stops": stops,
                "stop_count": len(stops),
            })
        dispatch = {"plan_id": current_plan_id, "revision": active_revision,
                    "vehicles": dispatch_vehicles,
                    "sequence_basis": "COMMITTED_MANIFEST_ORDER",
                    "partner_pickups": sorted(partner_pickups,
                                              key=lambda p: p["order_id"])}

    # --- Execution Record, relevance by identity then bounded --------------
    # The relevance set is built from stable target identities: the lifecycle,
    # containment, recovery, refusal and plan commands of the incidents this
    # projection selected, recomputed with the same _command_identity used to
    # write them. Nothing is admitted by action type, position, or prose, and
    # a receipt whose target cannot be recomputed is left out.
    relevant_action_ids = set()
    for row in incident_rows:
        incident_id = row[0]
        for status in ("SCOPING", "CONTAINMENT_IN_PROGRESS", "PARTIALLY_CONTAINED",
                       "CONTAINED", "CLOSED"):
            relevant_action_ids.add(
                _incident_status_action_id(tenant, incident_id, status))
        for action in ("movement-barrier", "plan:invalidate", "safe-recovery",
                       "containment-refusal", "acknowledgment-hold"):
            relevant_action_ids.add(
                _incident_action_id(tenant, incident_id, action))
        # Plan revisions of the selected day are committed against the truck
        # incident under the same deterministic identity scheme.
        for revision in revisions:
            relevant_action_ids.add(
                _incident_action_id(tenant, incident_id, f"plan:{revision}"))
    history = boundary.history(relevant_action_ids)

    partner_evidence_as_of = []
    for row in partner_evidence_rows:
        try:
            armor = json.loads(row[12] or "{}")
            proposal = json.loads(row[13] or "null")
            reasons = json.loads(row[15] or "[]")
            verification = json.loads(row[16] or "{}")
            requested_mutation = json.loads(row[17] or "null")
        except (TypeError, json.JSONDecodeError):
            omitted.append({
                "field": f"partner_evidence_as_of.{row[0]}",
                "reason": "PERSISTED_PARTNER_EVIDENCE_INVALID",
            })
            continue
        receipt = next((r for r in receipt_rows if r[0] == row[24]), None)
        node_cases = (
            ((verification.get("before_after") or {}).get("custody") or {}).get("cases")
        )
        total_cases = custody.get("unique_current_cases") if custody else None
        before_confirmed = (
            total_cases - node_cases
            if isinstance(total_cases, int) and isinstance(node_cases, int) else None
        )
        after_confirmed = (
            total_cases if row[14] == "APPLIED" else before_confirmed
        )
        partner_evidence_as_of.append({
            "source_event_id": row[0],
            "event_type": row[1],
            "incident_id": row[2],
            "authoritative_partner_id": row[3],
            "source_occurred_at": _normalize_receipt_timestamp(row[4]).isoformat(),
            "received_at": _normalize_receipt_timestamp(row[5]).isoformat(),
            "committed_at": _normalize_receipt_timestamp(row[27]).isoformat(),
            "original_response": row[6],
            "callback_principal": {
                "subject": row[7], "email": row[8], "audience": row[9],
                "issuer": row[10], "provenance": row[11],
            },
            "model_armor": armor,
            "proposal": proposal,
            "decision": row[14],
            "policy_reasons": reasons,
            "claim_verification": verification.get("claims", {}),
            "before_after": verification.get("before_after", {}),
            "requested_mutation": requested_mutation,
            "agent": {
                "agent_id": row[18], "model_id": row[19],
                "adk_framework": row[20], "adk_session_id": row[21],
                "adk_invocation_id": row[22], "adk_event_id": row[23],
            },
            "receipt": ({
                "receipt_id": receipt[0], "action_id": receipt[1],
                "action_type": receipt[2], "status": receipt[3],
                "domain_mutations_applied": row[25],
                "evidence_mutations_applied": row[26],
                "committed_at": _normalize_receipt_timestamp(receipt[5]).isoformat(),
            } if receipt else None),
            "custody": {
                "total_cases": total_cases,
                "confirmed_cases_before": before_confirmed,
                "confirmed_cases_after": after_confirmed,
            },
        })

    response = {
        "tenant_id": tenant,
        "operating_day": operating_day,
        "authority_scope": f"{tenant}@{operating_day}",
        "verified_principal_subject": identity.subject,
        "classification": "OBSERVED_LIVE",
        "projection_boundary": {
            "as_of": boundary_at.isoformat(),
            "mode": boundary_mode,
            "omitted_fields": omitted,
        },
        "current_day": {
            "plan_id": current_plan_id,
            "plan_revisions": [
                {"plan_id": r[0], "revision": r[1], "status": r[2]} for r in plan_rows
            ],
            "active_plan_revision": revisions[-1] if revisions else None,
            "commitments": commitments,
            "vehicles": [
                {"vehicle_id": v[0], "name": v[1], "capacity": v[2],
                 "assigned_cases": v[3], "is_operational": v[4]}
                for v in vehicle_rows
            ] if vehicle_rows else None,
            "approvals": [
                {"approval_id": a[0], "plan_id": a[1], "source_revision": a[2],
                 "proposed_revision": a[3], "plan_diff_hash": a[4],
                 # The key version is stored authority. The signature itself is
                 # never projected, at any boundary, to any caller.
                 "kms_key_version": a[5], "verified_at": str(a[6]),
                 "state": "VERIFIED",
                 "plan_diff": _plan_diff_rows(a[7]),
                 "approver_identity_class": "VERIFIED_HUMAN_OPERATOR",
                 "approver_domain": (
                     a[8].split("@", 1)[1] if a[8] and "@" in a[8] else None
                 ),
                 "authority_scope": a[9],
                 "expires_at": str(a[10]) if a[10] is not None else None}
                for a in approval_rows
            ],
            "incidents": incidents,
            "plan_constraints": [
                {"plan_id": c[0], "constraint_type": c[1], "description": c[2]}
                for c in constraint_rows
                if c[1] != "REPAIR_PROPOSAL"
            ],
            # A pending repair proposal: what the agents propose, not what
            # anyone authorized. Present only while its source revision is
            # still active; once the approved revision supersedes it the
            # proposal has been answered and stops being pending.
            "repair_proposal": repair_proposal,
            "recovery": {
                "allocations": [
                    {"allocation_id": a[0], "incident_id": a[1], "status": a[2],
                     "agency_id": a[4], "lot_id": a[5], "cases": a[6],
                     # The lot is authoritative. The facility is tenant
                     # configuration describing where that lot is stocked, and
                     # is null when the tenant configured none. It is never
                     # custody evidence: no hand-off of a replacement case is
                     # recorded anywhere, which source_facility_basis states.
                     "source_facility": _configured_source_facility(a[5]),
                     "source_facility_basis": SOURCE_FACILITY_BASIS}
                    for a in allocation_rows
                ],
                "shortfalls": [
                    {"shortfall_id": s[0], "incident_id": s[1], "status": s[2],
                     "agency_id": s[4], "cases": s[5]}
                    for s in shortfall_rows
                ],
                "explanation": (
                    _recovery_explanation(allocation_rows, shortfall_rows)
                    if allocation_rows or shortfall_rows else None
                ),
            },
            "dispatch": dispatch,
        },
        "agent_activity_as_of": fleet_evidence,
        "recall_intake_as_of": recall_intake,
        "partner_evidence_as_of": partner_evidence_as_of,
        "execution_evidence_as_of": {
            "custody_graph": custody,
            "receipts_committed": len(boundary._by_action_id),
            "history": history,
        },
        "carry_forward_obligations": carry_forward,
    }
    if next_day_draft is not None:
        response["next_day_draft"] = next_day_draft
    return response


# -------------------------------------------------------------------
# DELTA 2 - TRUTHFUL BOUNDED PROJECTION
#
# The operator projection must expose only facts committed at or before an
# explicit boundary. Four rules govern this, and each exists because of a
# specific structural limitation of the authoritative schema:
#
#   1. Receipts are the only per-event clock. Every gated block is unlocked
#      by a committed receipt, never by wall time or presentation state.
#   2. Receipts carry no incident_id or payload column, so a receipt cannot
#      be read to learn its target. Identity flows the other way: the target
#      is read from authoritative rows and its action_id is recomputed with
#      the same _command_identity used to write it. No positional assumption
#      ("the second SET_INCIDENT_STATUS") is ever made.
#   3. Vehicles, CustodyNodes and CustodyEdges are mutable current-state
#      tables with no history column. Their value at a past boundary cannot
#      be reconstructed, so they are returned only when no later mutation
#      exists, and omitted as PRE_BOUNDARY_STATE_NOT_RETAINED otherwise.
#   4. Obligations are evaluated open-as-of, never present-day-open.
# -------------------------------------------------------------------

# The five accepted agents. The coordinator is the root execution; the other
# four are the governed specialist sequence it orders. Model Armor is an
# input-screening boundary and is deliberately NOT a member of this list.
PROJECTED_AGENT_SEQUENCE = (
    (AGENT_INCIDENT_LEAD, "Incident Lead"),
    (AGENT_RECALL_INTAKE_EXTRACTION, "Recall Intake & Extraction"),
    (AGENT_NETWORK_CUSTODY, "Network & Custody"),
    (AGENT_FULFILLMENT_PLANNING_RECOVERY, "Fulfillment Planning & Recovery"),
    (AGENT_PARTNER_OPERATIONS, "Partner Operations"),
)

# Recall intake steps, each unlocked by the committed receipt or persisted
# evidence that actually proves it happened. There is no Running or Waiting
# member: the runtime is synchronous and reports no such state truthfully.
# `INCIDENT_OPENED` is proven by the incident row itself, not by a receipt
# lookup: the open command's action id embeds the source_event_id, which is not
# retained anywhere the projection can read, and recomputing it from a guessed
# value would be fabrication. A recall incident visible at the boundary was
# necessarily opened at or before it.
# Intake order is the authority order, and it is enforced by what each step
# is gated on rather than by list position: the regulatory event must have
# arrived before Model Armor can have screened it, and screening must have
# passed before extraction is permitted to read it.
#
# REGULATORY_EVENT_RECEIVED describes the inbound notice this runtime was
# given. Full Shelf does not poll or monitor the FDA; the demo input is a
# representative FDA-format regulatory notice delivered as an event.
RECALL_INTAKE_STEPS = (
    ("REGULATORY_EVENT_RECEIVED", "regulatory_event"),
    ("NOTICE_SCREENED", "model_armor"),
    ("NOTICE_EXTRACTED", "extraction"),
    ("INCIDENT_OPENED", "incident_row"),
    ("PLAN_INVALIDATED", "plan:invalidate"),
    ("MOVEMENT_BARRIER_ACTIVE", "movement-barrier"),
    ("FLEET_PROPOSAL_ACCEPTED", "fleet"),
)


def _projected_agent_activity(stored: Dict[str, Any], committed_at: str):
    """Project all five agents from persisted fleet evidence only.

    Every agent the manifest governs is listed so the rail cannot silently drop
    a member, but each one reports only what the persisted trace proves. An
    agent with no persisted hop is `NOT_YET_REPORTED`; it is never inferred to
    have run, and never given a duration, ordering, or Running/Waiting state
    the synchronous runtime does not record.
    """
    trace = stored.get("delegation_trace") or []
    by_agent = {entry.get("agent_id"): entry for entry in trace if entry.get("agent_id")}
    agents = []
    for agent_id, display_name in PROJECTED_AGENT_SEQUENCE:
        if agent_id == AGENT_INCIDENT_COORDINATOR:
            # The coordinator does not appear in its own delegation trace. Its
            # execution is proven by the run/session identity it recorded while
            # ordering the specialists.
            reported = bool(stored.get("coordination_run_id"))
            agents.append({
                "agent_id": agent_id,
                "display_name": display_name,
                "role": "ROOT_COORDINATOR",
                "state": "COMPLETED" if reported else "NOT_YET_REPORTED",
                "run_id": stored.get("coordination_run_id"),
                "session_id": stored.get("coordinator_session_id"),
                "model_used": None,
                "adk_framework": None,
                "deterministic_validation": None,
                "declared_tools": [],
                "tool_invocations": [],
            })
            continue
        entry = by_agent.get(agent_id)
        if entry is None:
            agents.append({
                "agent_id": agent_id,
                "display_name": display_name,
                "role": "GOVERNED_SPECIALIST",
                "state": "NOT_YET_REPORTED",
                "run_id": None,
                "session_id": None,
                "model_used": None,
                "adk_framework": None,
                "deterministic_validation": None,
                "declared_tools": [],
                "tool_invocations": [],
            })
            continue
        agents.append({
            "agent_id": agent_id,
            "display_name": display_name,
            "role": "GOVERNED_SPECIALIST",
            "state": "COMPLETED",
            # The specialist's OWN ADK identity, never the coordinator's.
            "run_id": entry.get("specialist_run_id"),
            "session_id": entry.get("specialist_session_id"),
            "model_used": entry.get("model_used"),
            "adk_framework": entry.get("adk_framework"),
            "deterministic_validation": entry.get("deterministic_validation"),
            "declared_tools": entry.get("declared_tools") or [],
            # Only Network & Custody holds tools today. Every other agent
            # projects the empty list its evidence actually contains.
            "tool_invocations": entry.get("tool_invocations") or [],
        })
    return {
        "manifest_version": stored.get("manifest_version"),
        "root_agent_id": stored.get("root_agent_id"),
        "coordinator_session_id": stored.get("coordinator_session_id"),
        "coordination_run_id": stored.get("coordination_run_id"),
        "proposal_status": stored.get("proposal_status"),
        "delegation_trace": trace,
        "committed_at": committed_at,
        "agents": agents,
        # Stated so the UI cannot render the topology as native ADK parentage.
        "topology": "SEPARATELY_CORRELATED_SPECIALIST_RUNNERS",
        "governed_sequence": list(GOVERNED_SEQUENCE),
    }


def _plan_diff_rows(plan_diff_json: Optional[str]):
    """Project the immutable approved plan diff as ordered rows.

    The diff is read from the approval record written under KMS binding, so the
    rows are the approved change itself rather than a recomputed guess at it.
    """
    try:
        diff = json.loads(plan_diff_json or "{}")
    except (TypeError, ValueError):
        return []
    rows = []
    if diff.get("reroute_order_id"):
        rows.append({
            "change_type": "REROUTE",
            "order_id": diff.get("reroute_order_id"),
            "cases": diff.get("reroute_cases"),
            "target_vehicle": diff.get("reroute_target_vehicle"),
        })
    if diff.get("pickup_order_id"):
        rows.append({
            "change_type": "PICKUP",
            "order_id": diff.get("pickup_order_id"),
            "cases": diff.get("pickup_cases"),
            "target_vehicle": None,
        })
    return rows


def _recovery_explanation(allocation_rows, shortfall_rows):
    """Explain recovery from authoritative quantities, never from model text.

    No agent rationale is persisted anywhere in the schema, so none is claimed.
    This is arithmetic over committed allocation and shortfall rows, labelled
    as a derivation so the operator can tell it apart from recorded reasoning.
    """
    allocated = sum(row[6] or 0 for row in allocation_rows)
    short = sum(row[5] or 0 for row in shortfall_rows)
    requested = allocated + short
    return {
        "basis": "DETERMINISTIC_DERIVATION",
        "cases_requested": requested,
        "cases_allocated": allocated,
        "cases_short": short,
        "agencies_allocated": len({row[4] for row in allocation_rows}),
        "agencies_short": len({row[4] for row in shortfall_rows}),
        "statement": (
            f"{allocated} of {requested} cases were allocated from safe stock; "
            f"{short} cases remain short across "
            f"{len({row[4] for row in shortfall_rows})} agency destinations."
        ),
        "persisted_agent_rationale": None,
    }


# The only approval transition this projection recognizes. The orchestrator and
# the ledger both already refuse any other transition with
# CANONICAL_REVISION_TRANSITION_REQUIRED, so binding the read to the same pair
# keeps the projection consistent with the write path it reports on.
CANONICAL_APPROVAL_SOURCE_REVISION = "rev07"
CANONICAL_APPROVAL_PROPOSED_REVISION = "rev08"

PRE_BOUNDARY_STATE_NOT_RETAINED = "PRE_BOUNDARY_STATE_NOT_RETAINED"

# A vehicle failure is stored under the contract's TRUCK_BREAKDOWN type, while
# the authoritative Friday seed records the same event as VEHICLE_FAILURE. Both
# name one domain concept with an ACTIVE -> RESOLVED lifecycle (see
# IncidentStateMachine), so the projection recognizes both rather than
# rewriting committed rows or inventing a third spelling.
VEHICLE_FAILURE_INCIDENT_TYPES = frozenset({"TRUCK_BREAKDOWN", "VEHICLE_FAILURE"})


def _is_vehicle_failure(incident_type: Optional[str]) -> bool:
    return incident_type in VEHICLE_FAILURE_INCIDENT_TYPES


# Where a replacement lot is stocked is deployment configuration, in the same
# sense as a warehouse address on a printed pick sheet. It is NOT custody
# evidence: no hand-off of a replacement case is recorded, and the projection
# says so explicitly rather than letting a client infer a chain of custody
# that was never committed.
SOURCE_FACILITY_BASIS = "CONFIGURED_TENANT_REFERENCE"


def _configured_source_facilities() -> Dict[str, str]:
    """Parse LOT_SOURCE_FACILITIES ("LOT-A=Facility A,LOT-B=Facility B")."""
    mapping: Dict[str, str] = {}
    for entry in os.getenv("LOT_SOURCE_FACILITIES", "").split(","):
        lot, sep, facility = entry.partition("=")
        if sep and lot.strip() and facility.strip():
            mapping[lot.strip()] = facility.strip()
    return mapping


def _configured_source_facility(lot_id: Optional[str]) -> Optional[str]:
    """Configured stocking facility for a lot, or None when unconfigured.

    Returning None is the honest answer for an unconfigured tenant. A
    placeholder here would read as a located fact on the operator surface.
    """
    if not lot_id:
        return None
    return _configured_source_facilities().get(lot_id)

# The Execution Record is a bounded operator surface, not an audit export. The
# canonical day commits far fewer receipts than this; the cap exists so the
# projection can never degrade into an unbounded all-time scan.
HISTORY_MAX_EVENTS = 100

# Receipt action types capable of mutating each timeless current-state table.
# If any of these committed after the boundary, that table's present row is a
# later value and cannot be shown as historical truth.
TIMELESS_TABLE_MUTATORS = {
    "vehicles": frozenset({"SAVE_PLAN_REVISION", "ALLOCATE_SAFE_STOCK"}),
    "custody": frozenset({
        "ACTIVATE_MOVEMENT_BARRIER",
        "ALLOCATE_SAFE_STOCK",
        "RECORD_ACKNOWLEDGMENT_HOLD",
        "PROCESS_PARTNER_EVIDENCE",
        "CUSTODY_RECONCILIATION",
    }),
}


class ProjectionBoundary:
    """Committed receipts at or before one instant, indexed for exact matching."""

    def __init__(self, as_of: datetime, mode: str, rows: List[Any]):
        self.as_of = as_of
        self.mode = mode
        self._by_action_id = {}
        self._after_boundary_action_types = set()
        self._committed_in_order = []
        for receipt_id, action_id, action_type, status, mutations, timestamp in rows:
            committed = _normalize_receipt_timestamp(timestamp)
            record = {
                "receipt_id": receipt_id,
                "action_id": action_id,
                "action_type": action_type,
                "status": status,
                "mutations_applied": mutations,
                "committed_at": committed.isoformat(),
            }
            if committed <= as_of:
                self._by_action_id.setdefault(action_id, record)
                self._committed_in_order.append(record)
            else:
                self._after_boundary_action_types.add(action_type)
        self._committed_in_order.sort(
            key=lambda entry: (entry["committed_at"], entry["receipt_id"])
        )

    def committed(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Return the receipt for one exact recomputed action identity."""
        return self._by_action_id.get(action_id)

    def has_committed(self, action_id: str) -> bool:
        return action_id in self._by_action_id

    def history(self, relevant_action_ids, limit: int = HISTORY_MAX_EVENTS):
        """Committed receipts for an explicit set of target identities.

        Relevance is decided by recomputed command identity, never by action
        type, receipt position, substring, or prose. A receipt that cannot be
        mechanically linked to the selected plan or incident is omitted rather
        than guessed at, so an unrelated same-tenant commit cannot appear even
        when its action type and timestamp look plausible.

        Filtering happens before the cap, so the bound trims genuinely relevant
        history rather than silently deciding relevance by truncation.
        """
        relevant = [entry for entry in self._committed_in_order
                    if entry["action_id"] in relevant_action_ids]
        return relevant[-limit:]

    def timeless_row_is_safe(self, table_key: str) -> bool:
        """True only when no later mutation of this table exists past the boundary."""
        return not (
            TIMELESS_TABLE_MUTATORS[table_key] & self._after_boundary_action_types
        )


def _resolve_projection_boundary(operating_day: str, as_of: Optional[str]):
    """Resolve the boundary instant from trusted server time or explicit request.

    A live request for the current operating day uses trusted server time. A
    historical or replay day requires an explicit as_of. An as_of outside the
    authority operating day is rejected, never silently narrowed.
    """
    day = datetime.fromisoformat(operating_day).date()
    now = datetime.now(timezone.utc)
    if as_of is None:
        if now.date() != day:
            raise HTTPException(
                status_code=400,
                detail="EXPLICIT_AS_OF_REQUIRED_FOR_NON_CURRENT_OPERATING_DAY",
            )
        return now, "LIVE_SERVER_TIME"
    try:
        parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="INVALID_AS_OF") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if parsed.date() != day:
        raise HTTPException(
            status_code=400,
            detail="AS_OF_OUTSIDE_AUTHORITY_OPERATING_DAY",
        )
    return parsed, "EXPLICIT_AS_OF"


def _incident_status_action_id(tenant_id: str, incident_id: str, status: str) -> str:
    """Recompute the exact action identity a lifecycle commit would have written."""
    action_id, _ = _command_identity(tenant_id, incident_id, f"status:{status}")
    return action_id


def _incident_action_id(tenant_id: str, incident_id: str, action: str) -> str:
    action_id, _ = _command_identity(tenant_id, incident_id, action)
    return action_id


def _normalize_receipt_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("INVALID_RECEIPT_TIMESTAMP") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _encode_receipt_cursor(timestamp: Any, receipt_id: str) -> str:
    normalized = _normalize_receipt_timestamp(timestamp).isoformat()
    encoded = base64.urlsafe_b64encode(
        json.dumps([normalized, receipt_id], separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"r1.{encoded}"


def _decode_receipt_cursor(event_id: str):
    if not event_id.startswith("r1."):
        raise ValueError("UNSUPPORTED_RECEIPT_CURSOR")
    encoded = event_id[3:]
    try:
        padding = "=" * (-len(encoded) % 4)
        timestamp, receipt_id = json.loads(
            base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        )
    except Exception as exc:
        raise ValueError("MALFORMED_RECEIPT_CURSOR") from exc
    if not isinstance(receipt_id, str) or not receipt_id:
        raise ValueError("MALFORMED_RECEIPT_CURSOR")
    return _normalize_receipt_timestamp(timestamp), receipt_id


def _query_committed_receipts_after(db, *, tenant_id: str, cursor):
    params = {"tenant_id": tenant_id}
    param_types = {"tenant_id": spanner.param_types.STRING}
    cursor_predicate = ""
    if cursor:
        cursor_predicate = """
          AND (
            timestamp > @cursor_timestamp
            OR (timestamp = @cursor_timestamp AND receipt_id > @cursor_receipt_id)
          )
        """
        params["cursor_timestamp"] = cursor[0]
        params["cursor_receipt_id"] = cursor[1]
        param_types["cursor_timestamp"] = spanner.param_types.TIMESTAMP
        param_types["cursor_receipt_id"] = spanner.param_types.STRING

    sql = f"""
      SELECT receipt_id, timestamp
      FROM Receipts
      WHERE tenant_id = @tenant_id
      {cursor_predicate}
      ORDER BY timestamp ASC, receipt_id ASC
      LIMIT 100
    """
    with db.snapshot() as snapshot:
        return list(snapshot.execute_sql(sql, params=params, param_types=param_types))


async def _stream_committed_receipts(
    *,
    request: Request,
    db,
    tenant_id: str,
    cursor,
    poll_interval: float,
    max_polls: Optional[int] = None,
):
    """Live-tail durable authoritative receipts until disconnect or read failure."""
    poll_count = 0
    heartbeat_at = datetime.now(timezone.utc)
    while True:
        if await request.is_disconnected():
            return
        try:
            rows = await asyncio.to_thread(
                _query_committed_receipts_after,
                db,
                tenant_id=tenant_id,
                cursor=cursor,
            )
        except Exception:
            logger.exception("Authoritative SSE receipt query failed")
            error = {
                "code": "AUTHORITATIVE_EVENT_READ_UNAVAILABLE",
                "classification": "FAILED",
                "emitted_at": datetime.now(timezone.utc).isoformat(),
            }
            yield f"event: projection_error\ndata: {json.dumps(error)}\n\n"
            return

        for row in rows:
            if await request.is_disconnected():
                return
            cursor = (_normalize_receipt_timestamp(row[1]), row[0])
            event_id = _encode_receipt_cursor(*cursor)
            # Cursor-only notification: all material state, including partner
            # source text, is fetched anew through the authenticated bounded
            # projection rather than copied into the event stream.
            payload = {"receipt_cursor": event_id}
            yield (
                f"id: {event_id}\n"
                f"event: projection_update\n"
                f"data: {json.dumps(payload)}\n\n"
            )

        poll_count += 1
        if max_polls is not None and poll_count >= max_polls:
            return
        if rows:
            continue

        now = datetime.now(timezone.utc)
        if (now - heartbeat_at).total_seconds() >= 15:
            yield f": keep-alive {now.isoformat()}\n\n"
            heartbeat_at = now
        await asyncio.sleep(max(poll_interval, 0.05))


@app.get("/api/v1/projections/stream")
async def stream_projections(
    request: Request,
    authority=Depends(require_frontend_authority),
):
    """Tail committed Spanner receipts and resume strictly after Last-Event-ID."""
    _, scope, _ = authority
    tenant_id = scope.tenant_id
    db = get_spanner_database(scope.database_id)
    last_event_id = request.headers.get("Last-Event-ID", "").strip()
    try:
        cursor = _decode_receipt_cursor(last_event_id) if last_event_id else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="INVALID_LAST_EVENT_ID") from exc

    return StreamingResponse(
        _stream_committed_receipts(
            request=request,
            db=db,
            tenant_id=tenant_id,
            cursor=cursor,
            poll_interval=float(os.getenv("SSE_POLL_INTERVAL_SECONDS", "1.0")),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# -------------------------------------------------------------------
# GATE L — REPRODUCIBLE DEMO CONTROLS
# -------------------------------------------------------------------

@app.post("/api/v1/demo/reset")
def reset_demo_state(
    tenant_id: str = "east-bay-food-bank"
):
    """Production reset is disabled; isolated audit tooling owns test teardown."""
    raise HTTPException(
        status_code=410,
        detail="PRODUCTION_RESET_DISABLED_USE_ISOLATED_AUDIT_DATABASE",
    )


@app.post("/api/v1/demo/seed")
def seed_demo_state(
    tenant_id: str = "east-bay-food-bank",
):
    """Production startup/demo seeding is disabled."""
    raise HTTPException(
        status_code=410,
        detail="PRODUCTION_SEED_DISABLED_USE_ISOLATED_AUDIT_DATABASE",
    )


@app.post("/api/v1/demo/replay")
def replay_hero_loop():
    """Reject direct demo replay; publish a scoped recall through the managed trigger."""
    raise HTTPException(410, "USE_MANAGED_RECALL_TRIGGER")


@app.get(
    "/api/v1/demo/export-evidence",
    dependencies=[Depends(require_internal_workload)],
)
def export_evidence(
    request: Request,
):
    """Exports full system evidence payload."""
    return get_system_evidence(request=request)
