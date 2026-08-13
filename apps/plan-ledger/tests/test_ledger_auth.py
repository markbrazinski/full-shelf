import importlib.util
import os
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from full_shelf_domain.identity import VerifiedGoogleIdentity


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
        "incident_id": "INC-ALT", "plan_id": "PLAN-ALT", "source_revision": "rev07",
        "proposed_revision": "rev08", "approval_id": "APP-ALT",
        "expires_at": "2099-01-01T00:00:00Z",
    })
    ledger_main.app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["detail"] == "OPERATOR_GOOGLE_ID_TOKEN_REQUIRED"
    assert kms_called is False
