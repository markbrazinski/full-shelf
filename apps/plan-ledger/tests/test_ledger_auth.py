import importlib.util
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from full_shelf_domain.identity import VerifiedGoogleIdentity
from full_shelf_domain.ledger_commands import LedgerCommand
from full_shelf_domain.kms import compute_plan_diff_hash
from full_shelf_domain.models import ApprovalEnvelope, PlanDiff


ledger_main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("plan_ledger_auth_main", ledger_main_path)
ledger_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger_main)
client = TestClient(ledger_main.app)


def configure_boundary(monkeypatch):
    monkeypatch.setenv("PLAN_LEDGER_AUDIENCE", "https://ledger.example.run.app")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_ACCOUNT_SUBJECT", "105774551577568412756")
    monkeypatch.setenv(
        "ORCHESTRATOR_SERVICE_ACCOUNT_EMAIL",
        "full-shelf-orchestrator-sa@example.iam.gserviceaccount.com",
    )


def test_missing_token_fails_before_spanner_read(monkeypatch):
    configure_boundary(monkeypatch)
    called = False

    def forbidden_database_call(tenant_id):
        nonlocal called
        called = True
        raise AssertionError("route logic ran before authentication")

    monkeypatch.setattr(ledger_main, "get_active_plan_revision", forbidden_database_call)
    response = client.get("/api/v1/plans/preview?tenant_id=audit-tenant")
    assert response.status_code == 401
    assert response.json()["detail"] == "GOOGLE_ID_TOKEN_REQUIRED"
    assert called is False


def test_signature_stripped_serverless_header_cannot_bypass_app_verification(monkeypatch):
    configure_boundary(monkeypatch)
    response = client.get(
        "/api/v1/evidence/system",
        headers={"X-Serverless-Authorization": "Bearer signature-was-stripped"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "GOOGLE_ID_TOKEN_REQUIRED"


def test_invalid_token_fails_before_route_logic(monkeypatch):
    configure_boundary(monkeypatch)

    def reject(self, authorization):
        from full_shelf_domain.identity import InvalidIdentityToken

        raise InvalidIdentityToken("bad signature")

    monkeypatch.setattr(ledger_main.GoogleOidcVerifier, "verify_authorization", reject)
    response = client.get(
        "/api/v1/evidence/system",
        headers={"Authorization": "Bearer unsigned-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "GOOGLE_ID_TOKEN_INVALID"


def test_unauthorized_subject_returns_403(monkeypatch):
    configure_boundary(monkeypatch)

    def reject(self, authorization):
        from full_shelf_domain.identity import UnauthorizedIdentity

        raise UnauthorizedIdentity("wrong subject")

    monkeypatch.setattr(ledger_main.GoogleOidcVerifier, "verify_authorization", reject)
    response = client.get(
        "/api/v1/evidence/system",
        headers={"Authorization": "Bearer google-signed-but-unapproved"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "GOOGLE_IDENTITY_NOT_ALLOWED"


def test_missing_boundary_configuration_returns_503(monkeypatch):
    monkeypatch.delenv("PLAN_LEDGER_AUDIENCE", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_SERVICE_ACCOUNT_SUBJECT", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_SERVICE_ACCOUNT_EMAIL", raising=False)
    response = client.get(
        "/api/v1/evidence/system",
        headers={"Authorization": "Bearer any-token"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "LEDGER_IDENTITY_BOUNDARY_NOT_CONFIGURED"


def test_correct_orchestrator_identity_reaches_allowed_ledger_route(monkeypatch):
    configure_boundary(monkeypatch)
    identity = VerifiedGoogleIdentity(
        subject="105774551577568412756",
        email="full-shelf-orchestrator-sa@example.iam.gserviceaccount.com",
        audience="https://ledger.example.run.app",
        issuer="https://accounts.google.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    monkeypatch.setattr(
        ledger_main.GoogleOidcVerifier,
        "verify_authorization",
        lambda self, authorization: identity,
    )
    response = client.get(
        "/api/v1/evidence/system",
        headers={"Authorization": "Bearer valid-google-token"},
    )
    assert response.status_code == 200
    assert response.json()["services"] == ["full-shelf-orchestrator", "full-shelf-plan-ledger"]


def test_every_ledger_api_route_has_workload_auth_dependency():
    unprotected = []
    for route in ledger_main.app.routes:
        if not getattr(route, "path", "").startswith("/api/v1/"):
            continue
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        if ledger_main.require_ledger_workload_identity not in dependency_calls:
            unprotected.append(route.path)
    assert unprotected == []


def test_approval_route_requires_independent_human_token_before_kms(monkeypatch):
    configure_boundary(monkeypatch)
    monkeypatch.setenv("OPERATOR_OAUTH_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setenv("ALLOWED_OPERATOR_SUBJECT", "operator-sub")
    monkeypatch.setenv("ALLOWED_OPERATOR_EMAIL", "operator@example.com")
    workload = VerifiedGoogleIdentity(
        subject="105774551577568412756",
        email="full-shelf-orchestrator-sa@example.iam.gserviceaccount.com",
        audience="https://ledger.example.run.app",
        issuer="https://accounts.google.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    ledger_main.app.dependency_overrides[ledger_main.require_ledger_workload_identity] = lambda: workload
    kms_called = False

    def forbidden_kms(**kwargs):
        nonlocal kms_called
        kms_called = True
        raise AssertionError("KMS ran without human identity")

    monkeypatch.setattr(ledger_main, "create_signed_approval_envelope", forbidden_kms)
    response = client.post("/api/v1/approvals/approve-and-activate", json={
        "command_id": "CMD-ALT", "idempotency_key": "alt", "tenant_id": "audit-tenant",
        "operating_day": "2026-08-14",
        "incident_id": "INC-ALT", "plan_id": "PLAN-ALT", "source_revision": "rev07",
        "proposed_revision": "rev08", "approval_id": "APP-ALT",
        "expires_at": "2099-01-01T00:00:00Z",
        "plan_diff": {
            "reroute_order_id": "ORDER-ALT-2", "reroute_cases": 12,
            "reroute_target_vehicle": "VEHICLE-ALT-2",
            "pickup_order_id": "ORDER-ALT-3", "pickup_cases": 7,
        },
    })
    ledger_main.app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["detail"] == "OPERATOR_GOOGLE_ID_TOKEN_REQUIRED"
    assert kms_called is False


def test_command_executor_routes_audit_tenant_to_isolated_database(monkeypatch):
    monkeypatch.setenv("SPANNER_DATABASE_ID", "full-shelf-main")
    monkeypatch.setenv("AUDIT_SPANNER_DATABASE_ID", "full-shelf-audit")
    monkeypatch.setenv("AUDIT_TENANT_IDS", "audit-canonical")
    selected = {}

    class Executor:
        def __init__(self, database, *, allowed_tenant_ids):
            selected["database"] = database
            selected["allowed_tenant_ids"] = allowed_tenant_ids

        def execute(self, command, caller):
            selected["command"] = command
            return "committed"

    monkeypatch.setattr(
        ledger_main,
        "get_spanner_database",
        lambda database_id=None: f"database:{database_id}",
    )
    monkeypatch.setattr(ledger_main, "SpannerLedgerCommandExecutor", Executor)
    command = LedgerCommand.model_validate(
        {
            "command_id": "CMD-AUDIT-ROUTE",
            "idempotency_key": "audit-route",
            "tenant_id": "audit-canonical",
            "incident_id": "INC-AUDIT",
            "agent_role": "FULFILLMENT_RECOVERY_PLANNER",
            "command_type": "SAVE_PLAN_REVISION",
            "expected_plan_revision": "rev07",
            "trace_id": "0123456789abcdef0123456789abcdef",
            "payload": {
                "plan_id": "PLAN-AUDIT",
                "revision": "rev07",
                "status": "ACTIVE",
            },
        }
    )
    caller = VerifiedGoogleIdentity(
        subject="orchestrator-subject",
        email="orchestrator@example.iam.gserviceaccount.com",
        audience="https://ledger.example.run.app",
        issuer="https://accounts.google.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    assert ledger_main._execute_command(command, caller) == "committed"
    assert selected["database"] == "database:full-shelf-audit"
    assert selected["allowed_tenant_ids"] == {
        "east-bay-food-bank",
        "audit-canonical",
    }


def test_human_route_persists_approval_before_separate_activation(monkeypatch):
    configure_boundary(monkeypatch)
    monkeypatch.setenv("SPANNER_DATABASE_ID", "full-shelf-main")
    operator = VerifiedGoogleIdentity(
        subject="operator-sub",
        email="operator@example.com",
        audience="client.apps.googleusercontent.com",
        issuer="https://accounts.google.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    workload = VerifiedGoogleIdentity(
        subject="orchestrator-sub",
        email="orchestrator@example.iam.gserviceaccount.com",
        audience="https://ledger.example.run.app",
        issuer="https://accounts.google.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    diff = PlanDiff(
        source_revision="rev07", proposed_revision="rev08",
        reroute_order_id="ORDER-ALT-2", reroute_cases=12,
        reroute_target_vehicle="VEHICLE-ALT-2",
        pickup_order_id="ORDER-ALT-3", pickup_cases=7,
        plan_diff_hash="",
    )
    diff.plan_diff_hash = compute_plan_diff_hash(diff)
    envelope = ApprovalEnvelope(
        approval_id="APP-ALT", tenant_id="east-bay-food-bank",
        operating_day="2026-08-14",
        authority_scope="east-bay-food-bank@2026-08-14",
        rev_id="rev08", principal_id=operator.subject,
        incident_id="INC-ALT", plan_id="PLAN-ALT", source_revision="rev07",
        proposed_revision="rev08", plan_diff=diff,
        kms_key_version="projects/p/keys/k/versions/1", kms_signature="signed",
        expires_at="2099-01-01T00:00:00Z",
    )
    calls = []

    def execute(command, caller):
        calls.append(command)
        return SimpleNamespace(
            receipt={"status": "SUCCESS", "command_type": command.command_type.value},
            idempotent_replay=False,
        )

    ledger_main.app.dependency_overrides[
        ledger_main.require_ledger_workload_identity
    ] = lambda: workload
    monkeypatch.setattr(ledger_main, "verify_human_operator", lambda token: operator)
    monkeypatch.setattr(ledger_main, "create_signed_approval_envelope", lambda **kwargs: envelope)
    monkeypatch.setattr(ledger_main, "verify_kms_approval_envelope", lambda value: True)
    monkeypatch.setattr(ledger_main, "_execute_command", execute)
    response = client.post(
        "/api/v1/approvals/approve-and-activate",
        headers={"X-Full-Shelf-Operator-Authorization": "Bearer human-token"},
        json={
            "command_id": "CMD-ALT", "idempotency_key": "alt",
            "tenant_id": "east-bay-food-bank", "operating_day": "2026-08-14",
            "incident_id": "INC-ALT",
            "plan_id": "PLAN-ALT", "source_revision": "rev07",
            "proposed_revision": "rev08", "approval_id": "APP-ALT",
            "expires_at": "2099-01-01T00:00:00Z",
            "plan_diff": {
                "reroute_order_id": "ORDER-ALT-2", "reroute_cases": 12,
                "reroute_target_vehicle": "VEHICLE-ALT-2",
                "pickup_order_id": "ORDER-ALT-3", "pickup_cases": 7,
            },
        },
    )
    ledger_main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [command.command_type.value for command in calls] == [
        "PERSIST_REPAIR_APPROVAL",
        "ACTIVATE_APPROVED_REPAIR_PLAN",
    ]
    assert calls[0].payload["plan_diff"]["reroute_order_id"] == "ORDER-ALT-2"
    assert calls[1].payload["approval_id"] == "APP-ALT"
    assert response.json()["approval_receipt"]["status"] == "SUCCESS"
    assert response.json()["activation_receipt"]["status"] == "SUCCESS"
