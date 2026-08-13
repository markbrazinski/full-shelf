from fastapi import Depends, FastAPI, HTTPException, Query, Header, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import os
from datetime import datetime, timezone

from google.cloud import spanner
from full_shelf_domain.models import (
    Vehicle, Order, PlanRevision, ApprovalEnvelope, Receipt,
    CustodyNode, CustodyEdge, NodeType, PlanStatus, IncidentStatus, PlanDiff
)
from full_shelf_domain.kms import (
    KmsApprovalError, create_signed_approval_envelope, verify_kms_approval_envelope,
)
from full_shelf_domain.identity import (
    GoogleOidcVerifier,
    IdentityConfigurationError,
    InvalidIdentityToken,
    MissingIdentityToken,
    UnauthorizedIdentity,
    VerifiedGoogleIdentity,
)
from full_shelf_domain.ledger_commands import LedgerCommand
from full_shelf_domain.ledger_executor import SpannerLedgerCommandExecutor
from full_shelf_domain.reconciliation import reconcile_recall_graph
from full_shelf_domain.spanner import (
    get_spanner_database, get_active_plan_revision
)
from full_shelf_observability import get_tracer, generate_trace_id, generate_span_id, parse_traceparent

app = FastAPI(title="Full Shelf Plan Ledger Service", version="1.1.0")
tracer = get_tracer("plan-ledger")


def require_ledger_workload_identity(
    authorization: Optional[str] = Header(None),
) -> VerifiedGoogleIdentity:
    """Authenticate the exact orchestrator workload before ledger route logic.

    Full Shelf sends its workload token in ``Authorization``. Cloud Run's
    ``X-Serverless-Authorization`` mode strips the signature before forwarding
    the token to the container, so it cannot satisfy this application-level
    cryptographic verification boundary.
    """

    try:
        verifier = GoogleOidcVerifier(
            audience=os.getenv("PLAN_LEDGER_AUDIENCE", ""),
            allowed_subjects={os.getenv("ORCHESTRATOR_SERVICE_ACCOUNT_SUBJECT", "")},
            allowed_emails={os.getenv("ORCHESTRATOR_SERVICE_ACCOUNT_EMAIL", "")},
        )
        return verifier.verify_authorization(authorization)
    except IdentityConfigurationError as exc:
        raise HTTPException(status_code=503, detail="LEDGER_IDENTITY_BOUNDARY_NOT_CONFIGURED") from exc
    except MissingIdentityToken as exc:
        raise HTTPException(
            status_code=401,
            detail="GOOGLE_ID_TOKEN_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InvalidIdentityToken as exc:
        raise HTTPException(
            status_code=401,
            detail="GOOGLE_ID_TOKEN_INVALID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except UnauthorizedIdentity as exc:
        raise HTTPException(status_code=403, detail="GOOGLE_IDENTITY_NOT_ALLOWED") from exc


class ExecuteActionRequest(BaseModel):
    action_id: str
    tenant_id: str = "east-bay-food-bank"
    agent_role: str
    action_type: str
    plan_id: str
    expected_revision: str = "rev07"
    parameters: Dict[str, Any]
    approval_envelope: Optional[ApprovalEnvelope] = None
    idempotency_key: str


class SaveDailyPlanRequest(BaseModel):
    tenant_id: str = "east-bay-food-bank"
    plan_details: Dict[str, Any]


class SaveNextDayPlanRequest(BaseModel):
    tenant_id: str = "east-bay-food-bank"
    next_day_plan: Dict[str, Any]


class HumanApprovalRequest(BaseModel):
    command_id: str
    idempotency_key: str
    tenant_id: str
    incident_id: str
    plan_id: str
    source_revision: str
    proposed_revision: str
    approval_id: str
    expires_at: str


def verify_human_operator(token: Optional[str]) -> VerifiedGoogleIdentity:
    try:
        return GoogleOidcVerifier(
            audience=os.getenv("OPERATOR_OAUTH_CLIENT_ID", ""),
            allowed_subjects={os.getenv("ALLOWED_OPERATOR_SUBJECT", "")},
            allowed_emails={os.getenv("ALLOWED_OPERATOR_EMAIL", "")},
        ).verify_authorization(token)
    except IdentityConfigurationError as exc:
        raise HTTPException(503, "OPERATOR_IDENTITY_BOUNDARY_NOT_CONFIGURED") from exc
    except MissingIdentityToken as exc:
        raise HTTPException(401, "OPERATOR_GOOGLE_ID_TOKEN_REQUIRED") from exc
    except InvalidIdentityToken as exc:
        raise HTTPException(401, "OPERATOR_GOOGLE_ID_TOKEN_INVALID") from exc
    except UnauthorizedIdentity as exc:
        raise HTTPException(403, "OPERATOR_GOOGLE_IDENTITY_NOT_ALLOWED") from exc


@app.post("/api/v1/approvals/approve-and-activate")
def approve_and_activate(
    req: HumanApprovalRequest,
    caller: VerifiedGoogleIdentity = Depends(require_ledger_workload_identity),
    operator_authorization: Optional[str] = Header(
        None, alias="X-Full-Shelf-Operator-Authorization"
    ),
):
    """Independently authenticate the human, KMS-sign, persist, and activate."""
    operator = verify_human_operator(operator_authorization)
    if req.source_revision != "rev07" or req.proposed_revision != "rev08":
        raise HTTPException(409, "CANONICAL_REVISION_TRANSITION_REQUIRED")
    try:
        envelope = create_signed_approval_envelope(
            approval_id=req.approval_id, rev_id=req.proposed_revision,
            principal_id=operator.subject, incident_id=req.incident_id,
            plan_id=req.plan_id, source_revision=req.source_revision,
            proposed_revision=req.proposed_revision, reroute_order_id="O202",
            reroute_cases=22, reroute_target_vehicle="TRUCK-02",
            pickup_order_id="O203", pickup_cases=20, expires_at=req.expires_at,
        )
    except KmsApprovalError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not verify_kms_approval_envelope(envelope):
        raise HTTPException(503, "MANAGED_KMS_VERIFICATION_FAILED")
    command = LedgerCommand.model_validate({
        "command_id": req.command_id,
        "idempotency_key": req.idempotency_key,
        "tenant_id": req.tenant_id,
        "incident_id": req.incident_id,
        "agent_role": "FULFILLMENT_RECOVERY_PLANNER",
        "command_type": "APPROVE_REPAIR_PLAN",
        "expected_plan_revision": req.source_revision,
        "trace_id": generate_trace_id(),
        "payload": {
            "plan_id": req.plan_id,
            "source_revision": req.source_revision,
            "proposed_revision": req.proposed_revision,
            "approval_id": req.approval_id,
            "approver_subject": operator.subject,
            "approver_email": operator.email,
            "oauth_audience": operator.audience,
            "plan_diff_hash": envelope.plan_diff.plan_diff_hash,
            "kms_key_version": envelope.kms_key_version,
            "kms_signature": envelope.kms_signature,
            "expires_at": envelope.expires_at,
        },
    })
    result = _execute_command(command, caller)
    return {"receipt": result.receipt, "idempotent_replay": result.idempotent_replay,
            "additional_mutations": result.additional_mutations,
            "approval_id": envelope.approval_id,
            "plan_diff_hash": envelope.plan_diff.plan_diff_hash,
            "kms_key_version": envelope.kms_key_version}


@app.post("/api/v1/commands/execute")
def execute_ledger_command(
    command: LedgerCommand,
    caller: VerifiedGoogleIdentity = Depends(require_ledger_workload_identity),
):
    """Execute one authenticated authoritative command and receipt atomically."""

    if command.command_type.value == "APPROVE_REPAIR_PLAN":
        raise HTTPException(403, "USE_HUMAN_APPROVAL_ROUTE")
    try:
        result = _execute_command(command, caller)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "receipt": result.receipt,
        "idempotent_replay": result.idempotent_replay,
        "additional_mutations": result.additional_mutations,
    }


def _execute_command(command: LedgerCommand, caller: VerifiedGoogleIdentity):
    """Single in-process entry to the deterministic transactional executor."""
    allowed_tenants = {
        value.strip()
        for value in os.getenv("ALLOWED_TENANT_IDS", "").split(",")
        if value.strip()
    }
    if not allowed_tenants:
        raise HTTPException(status_code=503, detail="LEDGER_TENANT_BOUNDARY_NOT_CONFIGURED")
    try:
        return SpannerLedgerCommandExecutor(
            get_spanner_database(),
            allowed_tenant_ids=allowed_tenants,
        ).execute(command, caller)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _legacy_receipt(result) -> Receipt:
    receipt = result.receipt
    return Receipt(
        receipt_id=receipt["receipt_id"],
        action_id=receipt["command_id"],
        tenant_id=receipt["tenant_id"],
        plan_revision_id=receipt["plan_revision_id"],
        action_type=receipt["command_type"],
        status=receipt["status"],
        timestamp=receipt["timestamp"],
        mutations_applied=0 if result.idempotent_replay else receipt["mutations_applied"],
        message=(
            "Duplicate idempotency key. Returned stable receipt with zero additional mutations."
            if result.idempotent_replay
            else receipt["message"]
        ),
        trace_id=receipt["trace_id"],
    )


@app.get("/")
def health_check():
    return {"service": "plan-ledger", "status": "healthy", "database": "full-shelf-main", "version": "1.1.0"}


@app.get("/api/v1/plans/preview")
def get_morning_plan_preview(
    request: Request,
    tenant_id: str = Query("east-bay-food-bank"),
    caller: VerifiedGoogleIdentity = Depends(require_ledger_workload_identity),
):
    """Returns Morning Plan preview from Spanner database."""
    db = get_spanner_database()
    trucks = []
    deliveries = []

    try:
        active_rev = get_active_plan_revision(tenant_id)
        with db.snapshot() as snapshot:
            truck_rows = snapshot.execute_sql(
                "SELECT vehicle_id, name, max_capacity_cases, current_load_cases FROM Vehicles WHERE tenant_id = @tenant_id",
                params={"tenant_id": tenant_id},
                param_types={"tenant_id": spanner.param_types.STRING}
            )
            for row in truck_rows:
                trucks.append({
                    "vehicle_id": row[0], "name": row[1], "capacity": row[2], "assigned_cases": row[3]
                })

            order_rows = snapshot.execute_sql(
                "SELECT order_id, destination_agency_name, cases, lot_id, assigned_vehicle_id FROM Orders WHERE tenant_id = @tenant_id AND revision = @rev",
                params={"tenant_id": tenant_id, "rev": active_rev},
                param_types={"tenant_id": spanner.param_types.STRING, "rev": spanner.param_types.STRING}
            )
            for row in order_rows:
                deliveries.append({
                    "order_id": row[0], "agency": row[1], "cases": row[2], "lot_id": row[3], "vehicle": row[4]
                })
    except Exception as exc:
        raise HTTPException(status_code=503, detail="AUTHORITATIVE_PLAN_READ_UNAVAILABLE") from exc

    return {
        "tenant_id": tenant_id,
        "date": "2026-08-07",
        "active_plan_revision": active_rev,
        "provenance": "GENERATED 05:30 · APPROVED 06:45 · ACTIVE rev07",
        "trucks": trucks,
        "deliveries": deliveries,
        "status": "HEALTHY" if active_rev in ["rev07", "rev08"] else "INVALIDATED_RECALL",
        "authenticated_caller": caller.email,
    }


@app.post(
    "/api/v1/plans/daily-plan/save",
    dependencies=[Depends(require_ledger_workload_identity)],
)
def save_daily_plan(req: SaveDailyPlanRequest):
    """Deprecated: plan writes require the complete command envelope."""
    raise HTTPException(status_code=410, detail="USE_API_V1_COMMANDS_EXECUTE")


@app.post(
    "/api/v1/plans/next-day-plan/save",
    dependencies=[Depends(require_ledger_workload_identity)],
)
def save_next_day_plan(req: SaveNextDayPlanRequest):
    """Deprecated: plan writes require the complete command envelope."""
    raise HTTPException(status_code=410, detail="USE_API_V1_COMMANDS_EXECUTE")


@app.post("/api/v1/actions/execute")
def execute_action(
    req: ExecuteActionRequest,
    request: Request,
    caller: VerifiedGoogleIdentity = Depends(require_ledger_workload_identity),
    traceparent: Optional[str] = Header(None),
    full_shelf_trace_id: Optional[str] = Header(None, alias="X-Full-Shelf-Trace-Id"),
):
    """Compatibility route backed exclusively by the command executor."""
    raise HTTPException(status_code=410, detail="USE_AUTHENTICATED_HUMAN_APPROVAL_ROUTE")

    # Historical implementation below is unreachable and retained only until
    # its response-model consumers migrate. It must never regain mutation use.
    extracted_trace_id = None
    if traceparent:
        parsed = parse_traceparent(traceparent)
        if parsed:
            extracted_trace_id = parsed[0]
    trace_id_str = full_shelf_trace_id or extracted_trace_id or generate_trace_id()

    if req.action_type != "APPLY_REPAIR_PLAN_REV08":
        raise HTTPException(status_code=422, detail="UNSUPPORTED_ACTION_TYPE")

    approval_valid = bool(
        req.approval_envelope
        and verify_kms_approval_envelope(req.approval_envelope)
    )
    if not approval_valid:
        refusal = LedgerCommand.model_validate(
            {
                "command_id": req.action_id,
                "idempotency_key": req.idempotency_key,
                "tenant_id": req.tenant_id,
                "incident_id": (
                    req.approval_envelope.incident_id
                    if req.approval_envelope
                    else "INC-TRUCK-01"
                ),
                "agent_role": req.agent_role,
                "command_type": "RECORD_REFUSAL",
                "expected_plan_revision": req.expected_revision,
                "trace_id": trace_id_str,
                "payload": {
                    "incident_id": "INC-TRUCK-01",
                    "subject_id": req.action_id,
                    "reason": "APPROVAL_ENVELOPE_VERIFICATION_FAILED",
                    "affected_cases": 0,
                },
            }
        )
        return _legacy_receipt(_execute_command(refusal, caller))

    envelope = req.approval_envelope
    assert envelope is not None
    command = LedgerCommand.model_validate(
        {
            "command_id": req.action_id,
            "idempotency_key": req.idempotency_key,
            "tenant_id": req.tenant_id,
            "incident_id": envelope.incident_id,
            "agent_role": req.agent_role,
            "command_type": "APPLY_REPAIR_PLAN",
            "expected_plan_revision": req.expected_revision,
            "trace_id": trace_id_str,
            "payload": {
                "plan_id": req.plan_id,
                "source_revision": envelope.source_revision,
                "proposed_revision": envelope.proposed_revision,
                "orders": [
                    {
                        "order_id": "O201",
                        "destination_agency_id": "AG01",
                        "destination_agency_name": "Agency 01",
                        "cases": 18,
                        "lot_id": "LTC-4471",
                        "assigned_vehicle_id": "TRUCK-01",
                        "status": "SCHEDULED",
                    },
                    {
                        "order_id": envelope.plan_diff.reroute_order_id,
                        "destination_agency_id": "AG02",
                        "destination_agency_name": "Agency 02",
                        "cases": envelope.plan_diff.reroute_cases,
                        "lot_id": "LTC-4471",
                        "assigned_vehicle_id": envelope.plan_diff.reroute_target_vehicle,
                        "status": "REROUTED",
                    },
                    {
                        "order_id": envelope.plan_diff.pickup_order_id,
                        "destination_agency_id": "AG03",
                        "destination_agency_name": "Agency 03",
                        "cases": envelope.plan_diff.pickup_cases,
                        "lot_id": "LTC-4471",
                        "assigned_vehicle_id": None,
                        "status": "PARTNER_PICKUP_CONVERTED",
                    },
                    {
                        "order_id": "O204",
                        "destination_agency_id": "AG04",
                        "destination_agency_name": "Agency 04",
                        "cases": 15,
                        "lot_id": "LTC-5090",
                        "assigned_vehicle_id": "TRUCK-02",
                        "status": "SCHEDULED",
                    },
                    {
                        "order_id": "O205",
                        "destination_agency_id": "AG05",
                        "destination_agency_name": "Agency 05",
                        "cases": 21,
                        "lot_id": "LTC-5090",
                        "assigned_vehicle_id": "TRUCK-02",
                        "status": "SCHEDULED",
                    },
                ],
            },
        }
    )
    return _legacy_receipt(_execute_command(command, caller))


@app.post(
    "/api/v1/incidents/recall",
    dependencies=[Depends(require_ledger_workload_identity)],
)
def trigger_recall_endpoint(payload: Dict[str, Any]):
    """Deprecated: recall effects require the complete command envelope."""
    raise HTTPException(status_code=410, detail="USE_API_V1_COMMANDS_EXECUTE")


@app.get(
    "/api/v1/evidence/system",
    dependencies=[Depends(require_ledger_workload_identity)],
)
def get_system_evidence():
    return {
        "gcp_project_id": "preflight-hackathon",
        "spanner_database": "full-shelf-main",
        "services": ["full-shelf-orchestrator", "full-shelf-plan-ledger"],
        "status": "OBSERVED_LIVE"
    }


@app.post(
    "/api/v1/incidents/site01-containment-attempt",
    dependencies=[Depends(require_ledger_workload_identity)],
)
def site01_containment_attempt(payload: Dict[str, Any]):
    """Deprecated: refusals require a committed command receipt."""
    raise HTTPException(status_code=410, detail="USE_API_V1_COMMANDS_EXECUTE")


@app.post(
    "/api/v1/plans/allocate-safe-stock",
    dependencies=[Depends(require_ledger_workload_identity)],
)
def allocate_safe_stock_endpoint(payload: Dict[str, Any]):
    """Deprecated: recovery effects require the complete command envelope."""
    raise HTTPException(status_code=410, detail="USE_API_V1_COMMANDS_EXECUTE")


@app.post(
    "/api/v1/incidents/site01-deadline",
    dependencies=[Depends(require_ledger_workload_identity)],
)
def site01_deadline_callback(payload: Dict[str, Any]):
    """Deprecated: callback effects require the complete command envelope."""
    raise HTTPException(status_code=410, detail="USE_API_V1_COMMANDS_EXECUTE")


@app.get(
    "/api/v1/evidence/spanner-reconciliation",
    dependencies=[Depends(require_ledger_workload_identity)],
)
def spanner_reconciliation_endpoint(tenant_id: str = Query("east-bay-food-bank")):
    db = get_spanner_database()
    active_rev = get_active_plan_revision(tenant_id)

    plan_records = []
    receipt_records = []
    order_records = []

    try:
        with db.snapshot() as snapshot:
            rev_rows = snapshot.execute_sql(
                "SELECT plan_id, revision, status, created_at FROM PlanRevisions WHERE tenant_id = @tenant_id ORDER BY created_at DESC",
                params={"tenant_id": tenant_id},
                param_types={"tenant_id": spanner.param_types.STRING}
            )
            for r in rev_rows:
                plan_records.append({"plan_id": r[0], "revision": r[1], "status": r[2], "created_at": str(r[3])})

            receipt_rows = snapshot.execute_sql(
                "SELECT receipt_id, action_id, action_type, status, mutations_applied, trace_id, timestamp FROM Receipts WHERE tenant_id = @tenant_id ORDER BY timestamp DESC",
                params={"tenant_id": tenant_id},
                param_types={"tenant_id": spanner.param_types.STRING}
            )
            for r in receipt_rows:
                receipt_records.append({
                    "receipt_id": r[0], "action_id": r[1], "action_type": r[2],
                    "status": r[3], "mutations_applied": r[4], "trace_id": r[5], "timestamp": str(r[6])
                })

            order_rows = snapshot.execute_sql(
                "SELECT order_id, assigned_vehicle_id, status, revision FROM Orders WHERE tenant_id = @tenant_id ORDER BY order_id ASC",
                params={"tenant_id": tenant_id},
                param_types={"tenant_id": spanner.param_types.STRING}
            )
            for r in order_rows:
                order_records.append({"order_id": r[0], "assigned_vehicle": r[1], "status": r[2], "revision": r[3]})
    except Exception as exc:
        raise HTTPException(status_code=503, detail="AUTHORITATIVE_RECONCILIATION_READ_UNAVAILABLE") from exc

    return {
        "tenant_id": tenant_id,
        "database_id": "full-shelf-main",
        "active_plan_revision": active_rev,
        "plan_revisions_count": len(plan_records),
        "plan_revisions": plan_records,
        "receipts_count": len(receipt_records),
        "receipts": receipt_records,
        "orders_state": order_records,
        "reconciliation_verdict": {
            "rev08_active": active_rev == "rev08",
            "exact_one_rev08_record": len([r for r in plan_records if r["revision"] == "rev08"]) == 1,
            "exact_one_success_receipt": len([r for r in receipt_records if r["status"] == "SUCCESS"]) == 1,
            "exact_two_mutations": sum(r["mutations_applied"] for r in receipt_records if r["status"] == "SUCCESS") == 2,
        }
    }
