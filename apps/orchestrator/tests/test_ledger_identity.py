import importlib.util
import os

import pytest

from full_shelf_domain.identity import IdentityConfigurationError


orchestrator_main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("orchestrator_identity_main", orchestrator_main_path)
orchestrator_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrator_main)


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None


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
