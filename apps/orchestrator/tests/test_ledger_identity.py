import importlib.util
import os

import pytest
from fastapi import HTTPException

from full_shelf_domain.identity import IdentityConfigurationError


orchestrator_main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("orchestrator_identity_main", orchestrator_main_path)
orchestrator_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrator_main)


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None


class FakeCommandResponse(FakeResponse):
    def __init__(self, status):
        self._status = status

    def json(self):
        return {
            "receipt": {
                "receipt_id": "RCT-ALT-DENIAL",
                "status": self._status,
                "message": "altered deterministic refusal",
            },
            "idempotent_replay": False,
            "additional_mutations": 0,
        }


def test_ledger_call_requires_explicit_url_and_audience(monkeypatch):
    monkeypatch.setattr(orchestrator_main, "PLAN_LEDGER_URL", "")
    monkeypatch.setattr(orchestrator_main, "PLAN_LEDGER_AUDIENCE", "")
    with pytest.raises(IdentityConfigurationError):
        orchestrator_main.post_to_plan_ledger("/api/v1/evidence/system", payload={})


def test_ledger_call_mints_exact_audience_token_and_uses_authorization(monkeypatch):
    audience = "https://ledger.example.run.app"
    monkeypatch.setattr(orchestrator_main, "PLAN_LEDGER_URL", audience)
    monkeypatch.setattr(orchestrator_main, "PLAN_LEDGER_AUDIENCE", audience)

    observed = {}

    def mint(target_audience):
        observed["audience"] = target_audience
        return "google-signed-token"

    def post(url, json, headers, timeout):
        observed.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(orchestrator_main, "fetch_google_id_token", mint)
    monkeypatch.setattr(orchestrator_main.httpx, "post", post)

    response = orchestrator_main.post_to_plan_ledger(
        "/api/v1/evidence/system",
        payload={"tenant_id": "audit-tenant"},
        trace_id="trace-123",
    )

    assert response.status_code == 200
    assert observed["audience"] == audience
    assert observed["url"] == f"{audience}/api/v1/evidence/system"
    assert observed["headers"]["Authorization"] == "Bearer google-signed-token"
    assert "X-Serverless-Authorization" not in observed["headers"]
    assert observed["headers"]["X-Full-Shelf-Trace-Id"] == "trace-123"


def test_denied_mutation_command_stops_orchestrator_processing(monkeypatch):
    monkeypatch.setattr(
        orchestrator_main,
        "post_to_plan_ledger",
        lambda *args, **kwargs: FakeCommandResponse("DENIED"),
    )
    with pytest.raises(HTTPException) as exc:
        orchestrator_main.execute_ledger_command(
            command_id="CMD-ALT-DENIED",
            idempotency_key="alt:denied",
            tenant_id="audit-tenant",
            incident_id="INC-ALT",
            agent_role="INCIDENT_COORDINATOR",
            command_type="SET_INCIDENT_STATUS",
            expected_plan_revision="rev42",
            trace_id="0123456789abcdef0123456789abcdef",
            payload={
                "incident_id": "INC-ALT",
                "expected_status": "DETECTED",
                "new_status": "SCOPING",
                "terminal_state": "NONE",
            },
        )
    assert exc.value.status_code == 409


def test_explicit_refusal_command_can_return_denial_receipt(monkeypatch):
    monkeypatch.setattr(
        orchestrator_main,
        "post_to_plan_ledger",
        lambda *args, **kwargs: FakeCommandResponse("DENIED"),
    )
    result = orchestrator_main.execute_ledger_command(
        command_id="CMD-ALT-REFUSAL",
        idempotency_key="alt:refusal",
        tenant_id="audit-tenant",
        incident_id="INC-ALT",
        agent_role="INCIDENT_COORDINATOR",
        command_type="RECORD_REFUSAL",
        expected_plan_revision="rev42",
        trace_id="0123456789abcdef0123456789abcdef",
        payload={
            "incident_id": "INC-ALT",
            "subject_id": "SITE-ALT",
            "reason": "ALTERED_UNCONFIRMED",
            "affected_cases": 2,
        },
        allow_denied=True,
    )
    assert result["receipt"]["status"] == "DENIED"
