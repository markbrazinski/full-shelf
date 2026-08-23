import json
import hashlib
import logging
import os
import base64
import asyncio
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, Any, Optional, List
from zoneinfo import ZoneInfo
from fastapi import Depends, FastAPI, Header, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
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

app = FastAPI(
    title="Full Shelf Fulfillment Orchestrator API",
    version="1.1.0",
    description="Production control plane for food-bank fulfillment operations governed by AGENTS.md and Build Book v1.1.",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)

tracer = get_tracer("orchestrator")
logger = logging.getLogger("full_shelf.orchestrator")

PUBLIC_HEALTH = "PUBLIC_HEALTH"
HUMAN_OPERATOR = "HUMAN_OPERATOR"
MANAGED_CALLBACK = "MANAGED_CALLBACK"
INTERNAL_WORKLOAD = "INTERNAL_WORKLOAD"
DISABLED_OR_REMOVED = "DISABLED_OR_REMOVED"

# This is the complete ingress contract. The middleware below denies any method
# and path absent from this table, and startup refuses any newly registered
# FastAPI route until it has been deliberately classified here.
ROUTE_AUTHENTICATION_MATRIX = {
    ("GET", "/"): PUBLIC_HEALTH,
    ("GET", "/healthz"): PUBLIC_HEALTH,
    ("POST", "/api/v1/orchestrator/approvals/approve-and-activate"): HUMAN_OPERATOR,
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


@app.middleware("http")
async def deny_unclassified_routes(request: Request, call_next):
    policy = ROUTE_AUTHENTICATION_MATRIX.get((request.method, request.url.path))
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


class RecallTriggerRequest(BaseModel):
    coordinator_id: str = Field(min_length=1, max_length=64)
    incident_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    notice_text: str = Field(min_length=1, max_length=20000)


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


def _verify_operator(authorization: Optional[str]):
    try:
        return GoogleOidcVerifier(
            audience=os.getenv("OPERATOR_OAUTH_CLIENT_ID", ""),
            allowed_subjects={os.getenv("ALLOWED_OPERATOR_SUBJECT", "")},
            allowed_emails={os.getenv("ALLOWED_OPERATOR_EMAIL", "")},
        ).verify_authorization(authorization)
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
    """Reject an ineligible configured model without triggering a paid health call."""
    if not PLAN_LEDGER_URL or not PLAN_LEDGER_AUDIENCE:
        raise RuntimeError("PLAN_LEDGER_URL and PLAN_LEDGER_AUDIENCE must be configured")
    if not all((MANAGED_CALLBACK_AUDIENCE, MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL,
                MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT)):
        raise RuntimeError("Managed callback OIDC configuration must be complete")
    # Construct every boundary at startup so a public platform ingress can never
    # become healthy with a missing application identity configuration.
    GoogleOidcVerifier(
        audience=os.getenv("OPERATOR_OAUTH_CLIENT_ID", ""),
        allowed_subjects={os.getenv("ALLOWED_OPERATOR_SUBJECT", "")},
        allowed_emails={os.getenv("ALLOWED_OPERATOR_EMAIL", "")},
    )
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
    """Commit a validated morning plan definition through the private ledger."""
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
            "ledger_mutation_attempted": False,
            "trace_id": trace_id,
        }

    extracted = extract_recall_entities_with_gemini_35(
        notice_text, correlation_id=trace_id
    )
    _persist_model_invocation_evidence(extracted, route="managed-pubsub-recall")
    if (not extracted.get("downstream_allowed")
            or extracted.get("lot_id") != recalled_lot_id):
        return {
            "hero_loop_status": "HALTED_FOR_MANUAL_REVIEW",
            "model_armor_screening": screening,
            "gemini_extraction": extracted,
            "ledger_mutation_attempted": False,
            "trace_id": trace_id,
        }

    inputs = _read_authoritative_recall_inputs(
        db, tenant_id=tenant_id, recalled_lot_id=recalled_lot_id,
        revision=active_revision,
    )
    open_command_id, open_key = _command_identity(
        tenant_id, incident_id, f"open:{source_event_id}"
    )
    open_result = execute_ledger_command(
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
                "product": extracted.get("product_name"),
                "hazard": extracted.get("hazard"),
                "action_required": extracted.get("action_required"),
            },
        },
    )

    def commit(action, command_type, payload, *, agent_role="INCIDENT_COORDINATOR",
               allow_denied=False):
        command_id, idempotency_key = _command_identity(tenant_id, incident_id, action)
        return execute_ledger_command(
            command_id=command_id, idempotency_key=idempotency_key,
            tenant_id=tenant_id, incident_id=incident_id, agent_role=agent_role,
            command_type=command_type, expected_plan_revision=active_revision,
            trace_id=trace_id, payload=payload, allow_denied=allow_denied,
        )

    scoping = commit("status:SCOPING", "SET_INCIDENT_STATUS", {
        "incident_id": incident_id, "expected_status": "DETECTED",
        "new_status": "SCOPING", "terminal_state": "NONE",
    })
    try:
        graph = _run_managed_custody_graph(
            db, tenant_id=tenant_id, lot_id=recalled_lot_id
        )
    except Exception as exc:
        raise HTTPException(503, "AUTHORITATIVE_GRAPH_READ_UNAVAILABLE") from exc
    if graph["unique_current_cases"] != inputs["recalled_total_cases"]:
        raise HTTPException(409, "CUSTODY_TOTAL_DOES_NOT_MATCH_RECALLED_LOT")
    if len(graph["unconfirmed_positions"]) != 1 or graph["unconfirmed_cases"] <= 0:
        raise HTTPException(409, "EXACTLY_ONE_UNCONFIRMED_POSITION_REQUIRED")
    unconfirmed_position = graph["unconfirmed_positions"][0]

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
    allocations, shortfalls = _derive_safe_recovery(
        incident_id=incident_id, safe_lots=inputs["safe_lots"],
        affected_orders=inputs["affected_orders"],
    )
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
        "model_armor_screening": screening,
        "gemini_35_extraction": extracted,
        "spanner_graph_reconstruction": graph,
        "safe_stock_recovery": {"allocations": allocations, "shortfalls": shortfalls},
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
            } for row in holds]),
        "confirmed_safe_inventory": [
            {"lot_id": row[0], "confirmed_cases": row[1]} for row in safe_lots
        ],
        "confirmed_transport_capacity": [
            {"vehicle_id": row[0], "max_cases": row[1], "current_load_cases": row[2]}
            for row in fleet
        ],
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
):
    """Project only committed facts from the configured verified authority."""
    identity, scope, operating_day = authority
    db = get_spanner_database(scope.database_id)
    with db.snapshot(multi_use=True) as snapshot:
        plans = list(snapshot.execute_sql(
            "SELECT plan_id, revision, status FROM PlanRevisions "
            "WHERE tenant_id=@tenant ORDER BY created_at",
            params={"tenant": scope.tenant_id},
            param_types={"tenant": spanner.param_types.STRING},
        ))
        approvals = list(snapshot.execute_sql(
            "SELECT approval_id, plan_id, source_revision, proposed_revision, "
            "plan_diff_hash, kms_key_version, verified_at FROM Approvals "
            "WHERE tenant_id=@tenant AND operating_day=@operating_day",
            params={
                "tenant": scope.tenant_id,
                "operating_day": datetime.fromisoformat(operating_day).date(),
            },
            param_types={
                "tenant": spanner.param_types.STRING,
                "operating_day": spanner.param_types.DATE,
            },
        ))
        incidents = list(snapshot.execute_sql(
            "SELECT incident_id, incident_type, status, terminal_state, details "
            "FROM Incidents WHERE tenant_id=@tenant ORDER BY created_at",
            params={"tenant": scope.tenant_id},
            param_types={"tenant": spanner.param_types.STRING},
        ))
    return {
        "tenant_id": scope.tenant_id,
        "operating_day": operating_day,
        "authority_scope": f"{scope.tenant_id}@{operating_day}",
        "verified_principal_subject": identity.subject,
        "classification": "OBSERVED_LIVE",
        "plan_revisions": [
            {"plan_id": row[0], "revision": row[1], "status": row[2]}
            for row in plans
        ],
        "approvals": [
            {"approval_id": row[0], "plan_id": row[1],
             "source_revision": row[2], "proposed_revision": row[3],
             "plan_diff_hash": row[4], "kms_key_version": row[5],
             "verified_at": str(row[6])}
            for row in approvals
        ],
        "incidents": [
            {"incident_id": row[0], "incident_type": row[1],
             "status": row[2], "terminal_state": row[3],
             "model_armor_correlation_id": (
                 json.loads(row[4] or "{}").get("model_armor_correlation_id")
             )}
            for row in incidents
        ],
    }


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
      SELECT receipt_id, action_id, plan_revision_id, action_type, status,
             message, timestamp, trace_id, caller_email
      FROM Receipts
      WHERE tenant_id = @tenant_id
      {cursor_predicate}
      ORDER BY timestamp ASC, receipt_id ASC
      LIMIT 100
    """
    with db.snapshot() as snapshot:
        return list(snapshot.execute_sql(sql, params=params, param_types=param_types))


def _receipt_projection(row) -> Dict[str, Any]:
    timestamp = _normalize_receipt_timestamp(row[6])
    event_id = _encode_receipt_cursor(timestamp, row[0])
    return {
        "event_id": event_id,
        "receipt_id": row[0],
        "action_id": row[1],
        "plan_revision_id": row[2],
        "action_type": row[3],
        "status": row[4],
        "message": row[5],
        "timestamp": timestamp.isoformat(),
        "correlation_trace_id": row[7],
        "committed_by": row[8],
    }


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
            event = _receipt_projection(row)
            cursor = (_normalize_receipt_timestamp(row[6]), row[0])
            payload = {
                "event_id": event["event_id"],
                "projection_type": "SPANNER_COMMITTED_RECEIPT",
                "classification": "OBSERVED_LIVE",
                "data": event,
                "emitted_at": datetime.now(timezone.utc).isoformat(),
            }
            yield (
                f"id: {event['event_id']}\n"
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
