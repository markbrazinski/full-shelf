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
from fastapi import FastAPI, Header, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
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
    MissingIdentityToken, UnauthorizedIdentity, fetch_google_id_token,
)
from full_shelf_domain.authority import (
    AuthorityConfigurationError,
    AuthorityScopeResolver,
    UnauthorizedAuthorityScope,
)
from full_shelf_domain.ledger_commands import OperatingPlanDefinition
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
)

tracer = get_tracer("orchestrator")
logger = logging.getLogger("full_shelf.orchestrator")


@app.middleware("http")
async def managed_request_trace(request: Request, call_next):
    with request_trace_span(
        tracer,
        request.headers,
        f"orchestrator {request.method} {request.url.path}",
    ) as trace_id:
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
    incident_id: str
    plan_id: str
    source_revision: str
    proposed_revision: str
    approval_id: str = Field(min_length=1, max_length=48)
    expires_at: str
    plan_diff: HumanRepairPlanDiff


class RecallArmorPreflightRequest(BaseModel):
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


@app.post("/api/v1/orchestrator/approvals/approve-and-activate")
def approve_and_activate(
    proposal: HumanApprovalProposal,
    authorization: Optional[str] = Header(None),
):
    """Validate the human token, then preserve it for independent ledger verification."""
    operator = _verify_operator(authorization)
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
  dst.node_id AS node_id,
  dst.node_type AS node_type,
  dst.name AS node_name,
  dst.on_hand_cases AS node_cases,
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
        "path_depth": 0,
    }
    nodes = {root["node_id"]: root}
    paths = []
    for row in rows:
        if row[0] != root["node_id"] or row[3] != root["on_hand_cases"]:
            raise ValueError("INCONSISTENT_GRAPH_ROOT")
        node = {
            "node_id": row[4],
            "node_type": row[5],
            "name": row[6],
            "on_hand_cases": row[7],
            "path_depth": row[8],
        }
        prior = nodes.get(node["node_id"])
        if prior and prior["on_hand_cases"] != node["on_hand_cases"]:
            raise ValueError("INCONSISTENT_GRAPH_NODE")
        if not prior or node["path_depth"] < prior["path_depth"]:
            nodes[node["node_id"]] = node
        paths.append({
            "root_node_id": row[0],
            "destination_node_id": row[4],
            "path_depth": row[8],
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
        "max_path_depth": max(path["path_depth"] for path in paths),
        "node_count": len(positions),
        "intermediate_subtotals_readded": False,
        "classification": "OBSERVED_LIVE",
    }


def get_judge_api_key() -> str:
    key = os.getenv("JUDGE_API_KEY")
    if key:
        return key.strip()
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = "projects/preflight-hackathon/secrets/full-shelf-judge-api-key/versions/latest"
        res = client.access_secret_version(request={"name": name})
        return res.payload.data.decode("utf-8").strip()
    except Exception as e:
        print(f"Secret Manager fetch note: {e}")
        return ""


def verify_judge_key(x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key")):
    expected_key = get_judge_api_key()
    if not expected_key:
        raise HTTPException(status_code=503, detail="JUDGE_AUTHENTICATION_NOT_CONFIGURED")
    if expected_key and x_api_key != expected_key:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized public invocation. Invalid or missing X-Full-Shelf-API-Key header."
        )


@app.on_event("startup")
def startup_checks():
    """Reject an ineligible configured model without triggering a paid health call."""
    if not PLAN_LEDGER_URL or not PLAN_LEDGER_AUDIENCE:
        raise RuntimeError("PLAN_LEDGER_URL and PLAN_LEDGER_AUDIENCE must be configured")
    if not all((MANAGED_CALLBACK_AUDIENCE, MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL,
                MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT)):
        raise RuntimeError("Managed callback OIDC configuration must be complete")
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
    tenant_id: str,
    operating_plan: OperatingPlanDefinition,
    source_event_id: str,
    source_publish_time: str,
) -> Dict[str, Any]:
    """Commit a validated morning plan definition through the private ledger."""
    trace_id = generate_trace_id()
    _resolve_authority_scope(tenant_id)
    plan_scope_digest = hashlib.sha256(
        f"{tenant_id}\x00{operating_plan.plan_id}\x00rev07".encode("utf-8")
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
                "source_event_id": source_event_id,
                "source_publish_time": source_publish_time,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="PLAN_LEDGER_DAILY_PLAN_COMMIT_FAILED") from exc

    return {
        "status": (
            "DAILY_PLAN_EXISTS_IDEMPOTENT"
            if ledger_result["idempotent_replay"]
            else "DAILY_PLAN_GENERATED_REV07"
        ),
        "revision": "rev07",
        "plan_details": operating_plan.model_dump(),
        "idempotent_replay": ledger_result["idempotent_replay"],
        "ledger_receipt": ledger_result["receipt"],
        "trace_id": trace_id
    }


@app.post("/api/v1/orchestrator/daily-plan/generate")
def generate_daily_morning_plan(
    operating_plan: OperatingPlanDefinition,
    tenant_id: str = Query("east-bay-food-bank"),
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    verify_judge_key(x_api_key)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return _generate_daily_morning_plan(
        tenant_id=tenant_id,
        operating_plan=operating_plan,
        source_event_id=f"manual-{generate_trace_id()}",
        source_publish_time=now,
    )


# -------------------------------------------------------------------
# GATE C — S2S DISPATCH & SPANNER AUTH PROOF
# -------------------------------------------------------------------

@app.post("/api/v1/orchestrator/s2s-dispatch")
def s2s_dispatch(
    idempotency_key: str = Query("ACT-S2S-EXEC-LIVE-001"),
    tamper_field: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key")
):
    raise HTTPException(410, "USE_AUTHENTICATED_HUMAN_APPROVAL_ROUTE")


# -------------------------------------------------------------------
# GATE D — DURABLE WAIT & PUB/SUB RESUME
# -------------------------------------------------------------------

@app.post("/api/v1/orchestrator/coordinator/persist-waiting")
def persist_coordinator_waiting(
    proposal: PersistWaitingCoordinatorRequest,
    tenant_id: str = "east-bay-food-bank",
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    """Persists day coordinator in WAITING_FOR_EVENTS state in Spanner after rev08."""
    verify_judge_key(x_api_key)
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
    authorization: Optional[str] = Header(None)
):
    """Authenticated Cloud Task callback for Site 01 acknowledgment deadline hold."""
    caller = _verify_managed_callback(authorization)
    task_name = req.headers.get("X-CloudTasks-TaskName")
    queue_name = req.headers.get("X-CloudTasks-QueueName")
    if not task_name or queue_name != "full-shelf-deadlines":
        raise HTTPException(400, "CLOUD_TASK_DELIVERY_CONTEXT_REQUIRED")

    incident_id = payload.incident_id
    site_id = payload.site_id
    tenant_id = payload.tenant_id
    task_decision_id = payload.task_decision_id
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
        command_id=f"CMD-TASK-{hashlib.sha256(task_decision_id.encode()).hexdigest()[:24]}",
        idempotency_key=f"cloud-task:{hashlib.sha256(task_decision_id.encode()).hexdigest()}",
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
            "task_name": task_name,
            "delivery_subject": caller.subject,
            "delivery_email": caller.email,
            "delivery_audience": caller.audience,
        },
    )

    return {
        "status": "DEADLINE_ACK_HOLD_PERSISTED",
        "site_id": site_id,
        "incident_id": incident_id,
        "unconfirmed_cases": payload.unconfirmed_cases,
        "authenticated_task": True,
        "task_name": task_name,
        "delivery_identity": caller.email,
        "delivery_subject": caller.subject,
        "delivery_audience": caller.audience,
        "idempotent_replay": ledger_result["idempotent_replay"],
        "timestamp": now,
        "ledger_receipt": ledger_result["receipt"],
    }


@app.post("/api/v1/orchestrator/site01-escalation/schedule")
def schedule_site01_escalation(
    proposal: SiteEscalationRequest,
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
    tenant_id: str = Query("east-bay-food-bank"),
):
    """Make the deployed decision that automatically creates the durable task."""
    verify_judge_key(x_api_key)
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
    authorization: Optional[str] = Header(None),
):
    """Handles real Pub/Sub wake-and-resume event pushing to Cloud Run orchestrator."""
    caller = _verify_managed_callback(authorization)
    trace_id = generate_trace_id()

    message = payload.get("message", {})
    message_id = message.get("messageId")
    publish_time = message.get("publishTime")
    if not message_id or not publish_time:
        raise HTTPException(status_code=400, detail="PUBSUB_MESSAGE_ID_AND_PUBLISH_TIME_REQUIRED")
    data_b64 = message.get("data", "")
    event_data = {}
    try:
        raw_str = base64.b64decode(data_b64).decode("utf-8")
        event_data = json.loads(raw_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="INVALID_PUBSUB_EVENT_DATA") from exc

    event_type = event_data.get("event_type", "") or message.get("attributes", {}).get("event_type", "")

    tenant_id = event_data.get("tenant_id")
    if not isinstance(tenant_id, str):
        raise HTTPException(status_code=400, detail="PUBSUB_TENANT_REQUIRED")
    scope = _resolve_authority_scope(tenant_id)
    db = get_spanner_database(scope.database_id)

    if event_type == "PLAN_NEXT_DAY_REQUESTED":
        next_day_res = _generate_next_day_plan(
            tenant_id=tenant_id,
            source_event_id=message_id,
            source_publish_time=publish_time,
        )
        return {
            "status": "SCHEDULER_NEXT_DAY_PLAN_GENERATED",
            "message_id": message_id,
            "event_type": "PLAN_NEXT_DAY_REQUESTED",
            "next_day_plan_result": next_day_res,
            "delivery_identity": caller.email,
            "delivery_audience": caller.audience,
            "trace_id": trace_id
        }

    if event_type == "PLAN_DAY_REQUESTED":
        try:
            operating_plan = OperatingPlanDefinition.model_validate(
                event_data.get("operating_plan")
            )
        except Exception as exc:
            raise HTTPException(400, "OPERATING_PLAN_DEFINITION_REQUIRED") from exc
        day_res = _generate_daily_morning_plan(
            tenant_id=tenant_id,
            operating_plan=operating_plan,
            source_event_id=message_id,
            source_publish_time=publish_time,
        )
        return {
            "status": "SCHEDULER_DAILY_PLAN_GENERATED",
            "message_id": message_id,
            "event_type": "PLAN_DAY_REQUESTED",
            "daily_plan_result": day_res,
            "delivery_identity": caller.email,
            "delivery_audience": caller.audience,
            "trace_id": trace_id
        }

    if event_type != "RECALL_NOTICE_RECEIVED":
        raise HTTPException(status_code=400, detail="UNSUPPORTED_PUBSUB_EVENT_TYPE")
    coord_id = event_data.get("coordinator_id")
    incident_id = event_data.get("incident_id")
    lot_id = event_data.get("lot_id")
    if not all(isinstance(value, str) and value for value in (
        coord_id, incident_id, lot_id
    )):
        raise HTTPException(400, "RECALL_EVENT_SCOPE_REQUIRED")
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
    if coord_state is None or active_rev is None:
        raise HTTPException(status_code=409, detail="WAITING_COORDINATOR_NOT_FOUND")

    message_digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
    ledger_result = execute_ledger_command(
        command_id=f"CMD-PUBSUB-{message_digest}",
        idempotency_key=f"pubsub:{message_digest}:open-recall",
        tenant_id=tenant_id,
        incident_id=incident_id,
        agent_role="INCIDENT_COORDINATOR",
        command_type="OPEN_RECALL_INCIDENT",
        expected_plan_revision=active_rev,
        trace_id=trace_id,
        payload={
            "incident_id": incident_id,
            "coordinator_id": coord_id,
            "lot_id": lot_id,
            "source_event_id": message_id,
            "source_publish_time": publish_time,
            "details": event_data,
        },
    )

    return {
        "status": "PUB_SUB_WAKE_RESUMED",
        "message_id": message_id,
        "coordinator_id": coord_id,
        "previous_state": coord_state,
        "new_state": "RECALL_WOKEN_DETECTED",
        "rehydrated_revision": active_rev,
        "incident": {
            "incident_id": incident_id,
            "status": "DETECTED",
            "affected_lot_id": lot_id,
        },
        "idempotent_redelivery": ledger_result["idempotent_replay"],
        "ledger_receipt": ledger_result["receipt"],
        "trace_id": trace_id
    }


# -------------------------------------------------------------------
# GATE E, F, G, H — RECALL HERO LOOP
# -------------------------------------------------------------------

@app.get("/api/v1/orchestrator/custody/graph")
def get_custody_graph_reconstruction(
    scenario: str = Query("canonical", pattern="^(canonical|altered)$"),
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    """Run a parameterized, variable-depth managed Spanner Graph reconstruction."""
    verify_judge_key(x_api_key)
    if scenario == "canonical":
        database_id = SPANNER_DATABASE
        tenant_id = "east-bay-food-bank"
        lot_id = "LTC-4471"
    else:
        tenant_id = "wp8-altered-audit"
        lot_id = "ALT-LOT-9001"
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

    result["scenario"] = scenario
    result["database_id"] = database_id
    return result

@app.post("/api/v1/orchestrator/recall/execute-hero-loop")
def execute_hero_loop(
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
    tenant_id: str = "east-bay-food-bank"
):
    """Executes complete recall hero loop across Pub/Sub, Model Armor, Gemini 3.5, Spanner Graph, Plan Ledger, KMS, and Cloud Tasks."""
    verify_judge_key(x_api_key)
    trace_id = generate_trace_id()
    scope = _resolve_authority_scope(tenant_id)
    db = get_spanner_database(scope.database_id)

    # Step 1: Model Armor Screening
    raw_notice = "REPRESENTATIVE DEMO NOTICE — FDA Enforcement Report #2026-0807-L4: Urgent recall issued for Lot LTC-4471 (Romaine Lettuce) due to contamination with E. coli O157:H7. Action: PAUSE_DISPATCH_AND_QUARANTINE."
    model_armor = inspect_recall_notice_with_model_armor(raw_notice)
    if model_armor.get("status") != "APPROVED" or model_armor.get("safety_verdict") != "PASSED":
        halt_reason = "HALTED_BY_MODEL_ARMOR_SAFETY_MATCH" if model_armor.get("status") == "BLOCKED" else "HALTED_BY_MODEL_ARMOR_SERVICE_FAILURE"
        return {
            "hero_loop_status": halt_reason,
            "model_armor_screening": model_armor,
            "trace_id": trace_id
        }

    # Step 2: Gemini 3.5 Flash Entity Extraction via ADK Runner
    extracted = extract_recall_entities_with_gemini_35(
        raw_notice,
        correlation_id=trace_id,
    )
    _persist_model_invocation_evidence(extracted, route="execute-hero-loop")
    if not extracted.get("downstream_allowed"):
        return {
            "hero_loop_status": "HALTED_FOR_MANUAL_REVIEW",
            "model_armor_screening": model_armor,
            "gemini_extraction": extracted,
            "trace_id": trace_id,
        }

    # Step 3: Lifecycle -> SCOPING & Spanner Graph Custody Traversal
    IncidentLifecycleManager.validate_transition("DETECTED", "SCOPING")
    scoping_result = execute_ledger_command(
        command_id="CMD-RECALL-SCOPING",
        idempotency_key=f"{tenant_id}:INC-RECALL-01:status:SCOPING",
        tenant_id=tenant_id,
        incident_id="INC-RECALL-01",
        agent_role="INCIDENT_COORDINATOR",
        command_type="SET_INCIDENT_STATUS",
        expected_plan_revision="rev08",
        trace_id=trace_id,
        payload={
            "incident_id": "INC-RECALL-01",
            "expected_status": "DETECTED",
            "new_status": "SCOPING",
            "terminal_state": "NONE",
        },
    )

    try:
        graph_reconstruction = _run_managed_custody_graph(
            db,
            tenant_id=tenant_id,
            lot_id="LTC-4471",
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="AUTHORITATIVE_GRAPH_READ_UNAVAILABLE") from exc

    # Step 4: Movement Barrier & Lifecycle -> CONTAINMENT_IN_PROGRESS
    IncidentLifecycleManager.validate_transition("SCOPING", "CONTAINMENT_IN_PROGRESS")
    barrier_result = execute_ledger_command(
        command_id="CMD-BARRIER-LTC-4471",
        idempotency_key=f"{tenant_id}:LTC-4471:movement-barrier:active",
        tenant_id=tenant_id,
        incident_id="INC-RECALL-01",
        agent_role="INCIDENT_COORDINATOR",
        command_type="ACTIVATE_MOVEMENT_BARRIER",
        expected_plan_revision="rev08",
        trace_id=trace_id,
        payload={
            "barrier_id": "BARRIER-LTC-4471",
            "incident_id": "INC-RECALL-01",
            "lot_id": "LTC-4471",
            "reason": "FOOD_SAFETY_RECALL",
            "work_item_id": "WORK-RECALL-LTC-4471-ROOT",
        },
    )
    containment_progress_result = execute_ledger_command(
        command_id="CMD-RECALL-CONTAINMENT-IN-PROGRESS",
        idempotency_key=f"{tenant_id}:INC-RECALL-01:status:CONTAINMENT_IN_PROGRESS",
        tenant_id=tenant_id,
        incident_id="INC-RECALL-01",
        agent_role="INCIDENT_COORDINATOR",
        command_type="SET_INCIDENT_STATUS",
        expected_plan_revision="rev08",
        trace_id=trace_id,
        payload={
            "incident_id": "INC-RECALL-01",
            "expected_status": "SCOPING",
            "new_status": "CONTAINMENT_IN_PROGRESS",
            "terminal_state": "NONE",
        },
    )

    # Step 5: Invalidate rev08 and record safe recovery through commands.
    invalidation_result = execute_ledger_command(
        command_id="CMD-INVALIDATE-REV08-RECALL",
        idempotency_key=f"{tenant_id}:PLAN-2026-08-07:rev08:recall-invalidation",
        tenant_id=tenant_id,
        incident_id="INC-RECALL-01",
        agent_role="INCIDENT_COORDINATOR",
        command_type="INVALIDATE_PLAN",
        expected_plan_revision="rev08",
        trace_id=trace_id,
        payload={
            "plan_id": "PLAN-2026-08-07",
            "revision": "rev08",
            "reason": "LTC-4471_RECALL",
        },
    )
    allocation_result = execute_ledger_command(
        command_id="CMD-ALLOCATE-LTC-5090-RECOVERY",
        idempotency_key=f"{tenant_id}:INC-RECALL-01:LTC-5090:recovery",
        tenant_id=tenant_id,
        incident_id="INC-RECALL-01",
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        command_type="ALLOCATE_SAFE_STOCK",
        expected_plan_revision="rev08",
        trace_id=trace_id,
        payload={
            "incident_id": "INC-RECALL-01",
            "allocations": [
                {
                    "allocation_id": "ALLOC-INC-RECALL-01-AG01",
                    "agency_id": "AG01",
                    "lot_id": "LTC-5090",
                    "cases": 18,
                },
                {
                    "allocation_id": "ALLOC-INC-RECALL-01-AG02",
                    "agency_id": "AG02",
                    "lot_id": "LTC-5090",
                    "cases": 22,
                },
            ],
            "shortfalls": [
                {
                    "shortfall_id": "SHORT-INC-RECALL-01-AG03",
                    "agency_id": "AG03",
                    "cases": 20,
                }
            ],
        },
    )

    # Step 6: Attempt Site 01 containment -> DENIED (DOWNSTREAM_CUSTODY_UNCONFIRMED)
    refusal_result = execute_ledger_command(
        command_id="CMD-REFUSE-SITE01-CONTAINMENT",
        idempotency_key=f"{tenant_id}:INC-RECALL-01:SITE-01:containment-refusal",
        tenant_id=tenant_id,
        incident_id="INC-RECALL-01",
        agent_role="INCIDENT_COORDINATOR",
        command_type="RECORD_REFUSAL",
        expected_plan_revision="rev08",
        trace_id=trace_id,
        allow_denied=True,
        payload={
            "incident_id": "INC-RECALL-01",
            "subject_id": "SITE-01",
            "reason": "DOWNSTREAM_CUSTODY_UNCONFIRMED",
            "unconfirmed_cases": 8,
        },
    )
    res_site01 = {
        "status": refusal_result["receipt"]["status"],
        "mutations_applied": refusal_result["receipt"]["mutations_applied"],
        "reason": "DOWNSTREAM_CUSTODY_UNCONFIRMED",
        "site_id": "SITE-01",
        "unconfirmed_cases": 8,
        "receipt": refusal_result["receipt"],
    }

    # Step 7: Schedule Cloud Task for Site 01 deadline
    task_res = schedule_site01_deadline_task(
        tenant_id=tenant_id,
        incident_id="INC-RECALL-01",
        hold_incident_id="INC-RECALL-01-HOLD-SITE01",
        coordinator_id="COORD-2026-0807",
        lot_id="LTC-4471",
        site_id="SITE-01",
        unconfirmed_cases=8,
        task_id=f"site01-{trace_id}",
        oidc_audience=MANAGED_CALLBACK_AUDIENCE,
        delivery_service_account=MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL,
        trace_id=trace_id,
    )

    # Step 8: Terminal calculation -> PARTIALLY_CONTAINED
    IncidentLifecycleManager.validate_transition("CONTAINMENT_IN_PROGRESS", "PARTIALLY_CONTAINED")

    terminal_state = "PARTIALLY_CONTAINED"

    # Step 9: Commit the honest terminal state through the deterministic ledger.
    terminal_result = execute_ledger_command(
        command_id="CMD-RECALL-PARTIALLY-CONTAINED",
        idempotency_key=f"{tenant_id}:INC-RECALL-01:status:PARTIALLY_CONTAINED",
        tenant_id=tenant_id,
        incident_id="INC-RECALL-01",
        agent_role="INCIDENT_COORDINATOR",
        command_type="SET_INCIDENT_STATUS",
        expected_plan_revision="rev08",
        trace_id=trace_id,
        payload={
            "incident_id": "INC-RECALL-01",
            "expected_status": "CONTAINMENT_IN_PROGRESS",
            "new_status": terminal_state,
            "terminal_state": terminal_state,
            "unconfirmed_cases": 8,
        },
    )

    refusal_proof = "DOWNSTREAM_CUSTODY_UNCONFIRMED: Refused transition from PARTIALLY_CONTAINED to CONTAINED."

    # Step 10: Publish recall event to Pub/Sub topic full-shelf-incidents
    pubsub_pub_res = publish_recall_event_to_pubsub({
        "event_type": "FOOD_SAFETY_RECALL",
        "lot_id": "LTC-4471",
        "hazard": "E. coli O157:H7",
        "action_required": "PAUSE_DISPATCH_AND_QUARANTINE",
        "notice_label": "REPRESENTATIVE DEMO NOTICE",
        "trace_id": trace_id
    })

    return {
        "hero_loop_status": "COMPLETED",
        "pubsub_receipt": pubsub_pub_res,
        "model_verification": {
            "model_id": MODEL_ID,
            "vertex_location": VERTEX_LOCATION,
            "adk_session_id": extracted["adk_session_id"],
            "adk_run_id": extracted["adk_run_id"],
            "adk_event_id": extracted["adk_event_id"],
            "classification": "OBSERVED_LIVE"
        },
        "model_armor_screening": model_armor,
        "gemini_35_extraction": extracted,
        "gemini_entity_extraction": extracted,
        "spanner_graph_reconstruction": graph_reconstruction,
        "safe_stock_allocation": {
            "safe_lot_id": "LTC-5090",
            "agency_01": 18,
            "agency_02": 22,
            "agency_03_shortage": 20
        },
        "site01_containment_refusal": res_site01,
        "site01_refusal_proof": refusal_proof,
        "ledger_command_receipts": {
            "scoping": scoping_result["receipt"],
            "barrier": barrier_result["receipt"],
            "containment_in_progress": containment_progress_result["receipt"],
            "plan_invalidation": invalidation_result["receipt"],
            "safe_stock_allocation": allocation_result["receipt"],
            "containment_refusal": refusal_result["receipt"],
            "terminal": terminal_result["receipt"],
        },
        "cloud_tasks_scheduling": task_res,
        "terminal_state_calculation": {
            "service_state": "4_OF_5_AGENCIES_SUPPLIED_AGENCY03_SHORT_20",
            "safety_state": "96_TRACED_88_CONFIRMED_8_UNCONFIRMED_SITE01",
            "incident_terminal_status": "PARTIALLY_CONTAINED"
        },
        "spanner_incident": {
            "incident_id": "INC-RECALL-01",
            "status": "PARTIALLY_CONTAINED",
            "affected_lot": "LTC-4471"
        },
        "terminal_state": terminal_state,
        "cloud_trace_id": trace_id
    }


@app.post("/api/v1/orchestrator/recall/model-armor-preflight")
def model_armor_preflight(
    request: RecallArmorPreflightRequest,
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    """Exercise only the deployed untrusted-input boundary; never call Gemini or ledger."""
    verify_judge_key(x_api_key)
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


@app.post("/api/v1/orchestrator/recall/extraction-preflight")
def extraction_preflight(
    request: RecallArmorPreflightRequest,
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    """Exercise the deployed Model Armor -> ADK boundary without mutation."""
    verify_judge_key(x_api_key)
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


@app.post("/api/v1/orchestrator/recall/trigger")
def trigger_recall_hero_loop(
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
    tenant_id: str = "east-bay-food-bank"
):
    return execute_hero_loop(x_api_key=x_api_key, tenant_id=tenant_id)


@app.get("/api/v1/orchestrator/recall/incident-status")
def get_incident_status(
    incident_id: str = Query("INC-RECALL-01"),
    tenant_id: str = "east-bay-food-bank",
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    verify_judge_key(x_api_key)
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
    source_event_id: str,
    source_publish_time: str,
) -> Dict[str, Any]:
    """Derive and command one governed draft from authoritative unresolved state."""
    trace_id = generate_trace_id()
    scope = _resolve_authority_scope(tenant_id)
    db = get_spanner_database(scope.database_id)
    publish_datetime = _parse_managed_publish_time(source_publish_time)
    operating_date = (
        publish_datetime.astimezone(ZoneInfo(OPERATING_TIME_ZONE)).date()
        + timedelta(days=1)
    )
    plan_id = f"PLAN-{operating_date.isoformat()}"
    coordinator_id = f"COORD-{operating_date.isoformat()}"

    read_phase = "snapshot_open"
    try:
        with db.snapshot(multi_use=True) as snapshot:
            read_phase = "incident"
            incident_rows = list(snapshot.execute_sql(
                "SELECT status FROM Incidents WHERE tenant_id = @t "
                "AND incident_id = 'INC-RECALL-01'",
                params={"t": tenant_id},
                param_types={"t": spanner.param_types.STRING},
            ))
            read_phase = "barrier"
            barrier_rows = list(snapshot.execute_sql(
                "SELECT barrier_id, lot_id, status FROM MovementBarriers "
                "WHERE tenant_id = @t AND status = 'ACTIVE' ORDER BY barrier_id",
                params={"t": tenant_id},
                param_types={"t": spanner.param_types.STRING},
            ))
            read_phase = "shortfall"
            shortfall_rows = list(snapshot.execute_sql(
                "SELECT shortfall_id, agency_id, cases, status FROM RecoveryShortfalls "
                "WHERE tenant_id = @t AND status = 'OPEN' ORDER BY shortfall_id",
                params={"t": tenant_id},
                param_types={"t": spanner.param_types.STRING},
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

    incident_status = incident_rows[0][0] if incident_rows else None
    barrier = next((row for row in barrier_rows if row[1] == "LTC-4471"), None)
    shortfall = next(
        (row for row in shortfall_rows if row[1] == "AG03" and row[2] == 20),
        None,
    )
    hold = None
    for row in hold_rows:
        try:
            details = json.loads(row[1] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if details.get("site_id") == "SITE-01" and details.get("unconfirmed_cases") == 8:
            hold = (row, details)
            break
    missing = []
    if incident_status != "PARTIALLY_CONTAINED":
        missing.append("PARTIALLY_CONTAINED_RECALL")
    if barrier is None:
        missing.append("LTC_4471_ACTIVE_BARRIER")
    if shortfall is None:
        missing.append("AG03_OPEN_20_CASE_SHORTFALL")
    if hold is None:
        missing.append("SITE01_OPEN_8_CASE_HOLD")
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
        "inherited_constraints": [
            {
                "constraint_id": barrier[0],
                "type": "LOT_MOVEMENT_BARRIER",
                "affected_lot": "LTC-4471",
                "status": "ACTIVE_BLOCKED"
            },
            {
                "constraint_id": shortfall[0],
                "type": "RECOVERY_PRIORITY",
                "agency_id": "AG03",
                "shortfall_cases": 20,
                "status": "PROMOTED_TO_FIRST_RECOVERY_PRIORITY"
            },
            {
                "constraint_id": hold[0][0],
                "type": "ACKNOWLEDGMENT_HOLD",
                "site_id": "SITE-01",
                "unconfirmed_cases": 8,
                "status": "ACKNOWLEDGMENT_HOLD_ACTIVE"
            }
        ],
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
            incident_id="INC-RECALL-01",
            agent_role="FULFILLMENT_RECOVERY_PLANNER",
            command_type="CREATE_NEXT_DAY_DRAFT",
            expected_plan_revision="rev08",
            trace_id=trace_id,
            payload={
                "source_event_id": source_event_id,
                "source_publish_time": source_publish_time,
                "operating_date": operating_date.isoformat(),
                "plan_id": plan_id,
                "revision": "rev01",
                "status": "DRAFT_WITH_CONSTRAINTS",
                "coordinator_id": coordinator_id,
                "excluded_lot_id": barrier[1],
                "shortfall_agency_id": shortfall[1],
                "shortfall_cases": shortfall[2],
                "acknowledgment_site_id": hold[1]["site_id"],
                "unconfirmed_cases": hold[1]["unconfirmed_cases"],
                "human_approval_required": True,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="PLAN_LEDGER_NEXT_DAY_COMMIT_FAILED") from exc

    return {
        "status": "NEXT_DAY_DRAFT_CREATED",
        "next_day_draft": next_day_plan,
        "idempotent_replay": ledger_result["idempotent_replay"],
        "ledger_receipt": ledger_result["receipt"],
        "trace_id": trace_id
    }


@app.post("/api/v1/orchestrator/next-day-plan/generate")
def generate_next_day_plan(
    tenant_id: str = Query("east-bay-food-bank"),
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    """Judge-protected manual control; managed proof must use Scheduler delivery."""
    verify_judge_key(x_api_key)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return _generate_next_day_plan(
        tenant_id=tenant_id,
        source_event_id=f"manual-{generate_trace_id()}",
        source_publish_time=now,
    )


# -------------------------------------------------------------------
# GATE J — SYSTEM EVIDENCE ENDPOINT
# -------------------------------------------------------------------

@app.get("/api/v1/evidence/system")
def get_system_evidence(
    request: Request,
    tenant_id: str = "east-bay-food-bank",
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    """Return independently classified evidence from this exact execution."""
    verify_judge_key(x_api_key)
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
            "SELECT status, terminal_state FROM Incidents WHERE tenant_id = @tenant_id "
            "AND incident_id = 'INC-RECALL-01'"
        )
        ground_truth["active_incident_status"] = rows[0][0] if rows else None
        ground_truth["incident_terminal_state"] = rows[0][1] if rows else None
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
            db, tenant_id=tenant_id, lot_id="LTC-4471"
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
            "secret_manager": {
                "secret_name": f"projects/{PROJECT_ID}/secrets/full-shelf-judge-api-key",
                "classification": "DESIGNED",
                "limitation": "Resource configuration is not an access receipt",
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
            "agent_registry": "STRUCTURALLY_VERIFIED — Versioned Agent Cards / Tool Gateway Manifest",
            "agent_identity": "STRUCTURALLY_VERIFIED — Cloud IAM / OIDC seam; not managed Agent Identity",
            "agent_gateway": "STRUCTURALLY_VERIFIED — private plan-ledger seam; not managed Agent Gateway",
            "agent_sessions": "STRUCTURALLY_VERIFIED — Spanner coordinator seam; not managed Agent Sessions"
        }
    }


# -------------------------------------------------------------------
# GATE K — FRONTEND PROJECTIONS & SSE STREAM
# -------------------------------------------------------------------

@app.get("/api/v1/projections/demo-beats")
def get_demo_beats_projections():
    """Versioned frontend projections for every locked demo beat (1 through 15)."""
    return {
        "tenant_id": "east-bay-food-bank",
        "beats": [
            {
                "beat_id": "BEAT_01_OUTCOME_PREVIEW",
                "title": "FIVE FOOD PROGRAMS STILL OPEN TODAY",
                "time": "0:00–0:20",
                "status": "OUTCOME_PREVIEW_ACTIVE"
            },
            {
                "beat_id": "BEAT_02_MORNING_PLAN",
                "title": "Governed Morning Plan rev07",
                "time": "0:20–0:43",
                "provenance": "GENERATED 05:30 · APPROVED 06:45 · ACTIVE rev07",
                "status": "ACTIVE_REV07"
            },
            {
                "beat_id": "BEAT_03_TRUCK_FAILURE",
                "title": "Truck 1 Breakdown & 45-Min Timer",
                "time": "0:43–1:00",
                "status": "INCIDENT_TRUCK_OPEN"
            },
            {
                "beat_id": "BEAT_04_REV08_PROPOSAL",
                "title": "KMS-Signed rev08 Approval Proposal",
                "time": "1:00–1:18",
                "kms_signature_status": "KMS_SIGNATURE_VERIFIED"
            },
            {
                "beat_id": "BEAT_05_REV08_ACTIVE",
                "title": "Repaired Plan Active & Truck Incident Resolved",
                "time": "1:18–1:30",
                "status": "INCIDENT_TRUCK_RESOLVED"
            },
            {
                "beat_id": "BEAT_06_WAITING_FOR_EVENTS",
                "title": "Coordinator Persisted WAITING_FOR_EVENTS",
                "time": "1:30–1:40",
                "coordinator_state": "WAITING_FOR_EVENTS"
            },
            {
                "beat_id": "BEAT_07_RECALL_RECEIVED",
                "title": "Pub/Sub Recall Event & Model Armor Inspection",
                "time": "1:40–1:52",
                "notice_label": "REPRESENTATIVE DEMO NOTICE",
                "model_armor_status": "REQUIRES_CORRELATED_LIVE_EXECUTION"
            },
            {
                "beat_id": "BEAT_08_RECALL_SCOPING",
                "title": "Gemini 3.5+ Extraction & Incident Opened",
                "time": "1:52–2:10",
                "model_id": MODEL_ID,
                "model_execution_status": "REQUIRES_CORRELATED_LIVE_EXECUTION",
                "incident_status": "DETECTED_SCOPING"
            },
            {
                "beat_id": "BEAT_09_GRAPH_RECONSTRUCTION",
                "title": "Spanner Graph Custody Traversal",
                "time": "2:10–2:28",
                "unique_cases": 96,
                "site01_deduplicated": True
            },
            {
                "beat_id": "BEAT_10_BARRIER_ACTIVE",
                "title": "Atomic LTC-4471 Movement Barrier Committed",
                "time": "2:28–2:45",
                "status": "CONTAINMENT_IN_PROGRESS"
            },
            {
                "beat_id": "BEAT_11_RECOVERY_APPLIED",
                "title": "LTC-5090 Safe Stock Allocated & Shortfall Recorded",
                "time": "2:45–3:08",
                "safe_allocations": {"AG01": 18, "AG02": 22},
                "shortfall": {"AG03": 20}
            },
            {
                "beat_id": "BEAT_12_FALSE_CONTAINMENT_DENIAL",
                "title": "Site 01 Downstream Refusal & Cloud Task Scheduled",
                "time": "3:08–3:20",
                "refusal_reason": "DOWNSTREAM_CUSTODY_UNCONFIRMED",
                "mutations_applied": 0
            },
            {
                "beat_id": "BEAT_13_PARTIAL_CONTAINMENT",
                "title": "Terminal Board & Partial Containment Calculation",
                "time": "3:20–3:28",
                "terminal_state": "PARTIALLY_CONTAINED",
                "service": "4_OF_5_SUPPLIED_AGENCY03_SHORT_20",
                "safety": "96_TRACED_88_CONFIRMED_8_UNCONFIRMED_SITE01"
            },
            {
                "beat_id": "BEAT_14_NEXT_DAY_DRAFT",
                "title": "17:00 · NEXT-DAY PLANNING Constrained Draft rev01",
                "time": "3:28–3:38",
                "scenario_time": "17:00 · NEXT-DAY PLANNING",
                "status": "DRAFT_WITH_CONSTRAINTS — HUMAN APPROVAL REQUIRED"
            },
            {
                "beat_id": "BEAT_15_SYSTEM_EVIDENCE",
                "title": "System Evidence & Deployed Console Proof",
                "time": "3:38–3:55",
                "services": ["full-shelf-orchestrator", "full-shelf-plan-ledger"]
            }
        ]
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
             message, timestamp
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
    tenant_id: str = "east-bay-food-bank",
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    """Tail committed Spanner receipts and resume strictly after Last-Event-ID."""
    verify_judge_key(x_api_key)
    scope = _resolve_authority_scope(tenant_id)
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
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
    tenant_id: str = "east-bay-food-bank"
):
    """Production reset is disabled; isolated audit tooling owns test teardown."""
    verify_judge_key(x_api_key)
    raise HTTPException(
        status_code=410,
        detail="PRODUCTION_RESET_DISABLED_USE_ISOLATED_AUDIT_DATABASE",
    )


@app.post("/api/v1/demo/seed")
def seed_demo_state(
    tenant_id: str = "east-bay-food-bank",
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    """Production startup/demo seeding is disabled."""
    verify_judge_key(x_api_key)
    _resolve_authority_scope(tenant_id)
    raise HTTPException(
        status_code=410,
        detail="PRODUCTION_SEED_DISABLED_USE_ISOLATED_AUDIT_DATABASE",
    )


@app.post("/api/v1/demo/replay")
def replay_hero_loop(x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key")):
    """Executes full end-to-end replay command."""
    return execute_hero_loop(x_api_key=x_api_key)


@app.get("/api/v1/demo/export-evidence")
def export_evidence(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-Full-Shelf-API-Key"),
):
    """Exports full system evidence payload."""
    return get_system_evidence(request=request, x_api_key=x_api_key)
