import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "bootstrap_wp3_operator.py"
spec = importlib.util.spec_from_file_location("operator_audit_session", SCRIPT)
operator_session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator_session)


def test_audit_session_listener_is_loopback_only():
    source = SCRIPT.read_text()
    assert 'AuditSessionServer(("127.0.0.1", args.port), Handler)' in source
    assert "0.0.0.0" not in source


def test_page_uses_gis_nonce_state_and_only_fixed_operations():
    page = operator_session._page(
        "client.apps.googleusercontent.com", "session-state", "gis-nonce"
    ).decode()
    assert "nonce: \"gis-nonce\"" in page
    assert "state: sessionState" in page
    assert "/session/approval" in page
    assert "/session/projection" in page
    assert "/session/sse" in page
    assert "/session/shutdown" in page
    assert "destination" not in page


def test_approval_payloads_are_fixed_to_canonical_and_altered_fixtures():
    payloads = operator_session._approval_payloads(
        "audit-final-canonical-20260814", "2026-08-14"
    )
    assert set(payloads) == {"canonical", "altered"}
    assert all(payload["tenant_id"] == "audit-final-canonical-20260814" for payload in payloads.values())
    assert all(payload["source_revision"] == "rev07" for payload in payloads.values())
    assert all(payload["proposed_revision"] == "rev08" for payload in payloads.values())


def test_helper_has_no_token_query_or_persistence_sink():
    source = SCRIPT.read_text()
    assert "Authorization\": f\"Bearer {credential}" in source
    assert "params={" not in source
    assert "print(credential" not in source
    assert "write_text" not in source
    assert "ORCHESTRATOR_URL" in source
    assert "--orchestrator-url" not in source
