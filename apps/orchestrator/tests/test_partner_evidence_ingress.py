from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import httpx

import main
from full_shelf_domain.identity import VerifiedGoogleIdentity
from full_shelf_domain.partner_evidence import PartnerCustodyProposal


CALLER = VerifiedGoogleIdentity(
    subject="partner-subject", email="partner@example.com",
    audience="https://orchestrator.example/partner-evidence",
    issuer="https://accounts.google.com",
    expires_at=datetime(2026, 8, 14, 11, tzinfo=timezone.utc),
)

REQUEST = {
    "event_type": "PARTNER_CUSTODY_EVIDENCE_RECEIVED",
    "source_event_id": "partner-event-1",
    "incident_id": "INC-2231",
    "original_text": "We pulled the remaining lettuce. Should be all good.",
    "source_occurred_at": "2026-08-14T10:15:00+00:00",
}

AUTHORITY = {
    "incident_id": "INC-2231", "incident_status": "PARTIALLY_CONTAINED",
    "terminal_state": "PARTIALLY_CONTAINED", "plan_id": "PLAN-2026-08-14",
    "plan_revision": "rev08", "plan_status": "INVALIDATED_RECALL",
    "work_item_id": "WORK-PCF-01", "partner_id": "PARTNER-AGENCY-01",
    "site_id": "SITE-01", "custody_node_id": "N-ST01",
    "custody_node_name": "Site 01", "lot_id": "LTC-4471",
    "expected_cases": 8, "expected_acknowledgment_status": "UNCONFIRMED",
    "requested_acknowledgment_status": "CONFIRMED",
    "custody_edge_id": "E-ST01", "custody_edge_cases": 8,
}


def _proposal():
    return PartnerCustodyProposal(
        incident_id="INC-2231", partner_id="PARTNER-AGENCY-01",
        site_id="SITE-01", custody_node_id="N-ST01", work_item_id="WORK-PCF-01",
        expected_acknowledgment_status="UNCONFIRMED",
        requested_acknowledgment_status="CONFIRMED",
        requested_mutation="CONFIRM_CUSTODY",
        rationale="Required factual claims are absent.", confidence=0.7,
    )


def test_partner_ingress_derives_scope_and_preserves_authenticated_provenance(monkeypatch):
    monkeypatch.setenv("PARTNER_CALLBACK_AUTHORITY_JSON", (
        '{"partner-subject":{"tenant_id":"audit-tenant",'
        '"partner_id":"PARTNER-AGENCY-01"}}'
    ))
    client = TestClient(main.app)
    main.app.dependency_overrides[main.require_partner_callback] = lambda: CALLER
    scope = MagicMock(database_id="audit-db")
    ledger_result = {
        "receipt": {"receipt_id": "RCT-PE", "status": "DENIED"},
        "idempotent_replay": False,
    }
    try:
        with (
            patch.object(main, "_utc_now", return_value=datetime(2026, 8, 14, 10, 16,
                                                                  tzinfo=timezone.utc)),
            patch.object(main, "_resolve_authority_scope", return_value=scope),
            patch.object(main, "get_spanner_database", return_value=MagicMock()),
            patch.object(main, "_read_partner_evidence_authority", return_value=AUTHORITY),
            patch.object(main, "inspect_recall_notice_with_model_armor", return_value={
                "status": "APPROVED", "safety_verdict": "PASSED",
                "correlation_id": "0123456789abcdef0123456789abcdef",
            }),
            patch.object(main, "run_partner_evidence_agent", new=AsyncMock(return_value=(
                _proposal(), {
                    "agent_id": "full-shelf.partner-operations.v2",
                    "model_id": "gemini-3.5-flash", "adk_framework": "google-adk/2.6.1",
                    "adk_session_id": "session", "adk_invocation_id": "invocation",
                    "adk_event_id": "event",
                },
            ))),
            patch.object(main, "execute_ledger_command", return_value=ledger_result) as ledger,
        ):
            response = client.post(
                "/api/v1/orchestrator/partner-evidence",
                headers={
                    "Authorization": "Bearer signed",
                    "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
                },
                json=REQUEST,
            )
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 200
    command = ledger.call_args.kwargs
    assert command["tenant_id"] == "audit-tenant"
    assert command["command_type"] == "PROCESS_PARTNER_EVIDENCE"
    assert command["allow_denied"] is True
    assert command["payload"]["partner_id"] == "PARTNER-AGENCY-01"
    assert command["payload"]["callback_subject"] == CALLER.subject
    assert command["payload"]["callback_provenance"] == "AUTHENTICATED_PARTNER_CALLBACK"
    assert command["payload"]["adk_invocation_id"] == "invocation"
    assert "tenant_id" not in REQUEST and "partner_id" not in REQUEST


def test_partner_ingress_forbids_caller_scope_overrides():
    client = TestClient(main.app)
    main.app.dependency_overrides[main.require_partner_callback] = lambda: CALLER
    try:
        response = client.post(
            "/api/v1/orchestrator/partner-evidence",
            json={**REQUEST, "tenant_id": "attacker", "partner_id": "attacker"},
        )
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 422


def test_partner_ingress_preserves_permanent_ledger_conflict_as_409(monkeypatch):
    monkeypatch.setenv(
        "PARTNER_CALLBACK_AUTHORITY_JSON",
        '{"partner-subject":{"tenant_id":"audit-tenant",'
        '"partner_id":"PARTNER-AGENCY-01"}}',
    )
    client = TestClient(main.app)
    main.app.dependency_overrides[main.require_partner_callback] = lambda: CALLER
    ledger_request = httpx.Request("POST", "https://ledger.example/commands")
    conflict = httpx.Response(409, request=ledger_request)
    try:
        with (
            patch.object(main, "_utc_now", return_value=datetime(
                2026, 8, 14, 10, 16, tzinfo=timezone.utc
            )),
            patch.object(main, "_resolve_authority_scope", return_value=MagicMock(
                database_id="audit-db"
            )),
            patch.object(main, "get_spanner_database", return_value=MagicMock()),
            patch.object(main, "_read_partner_evidence_authority", return_value=AUTHORITY),
            patch.object(main, "inspect_recall_notice_with_model_armor", return_value={
                "status": "APPROVED", "safety_verdict": "PASSED",
                "correlation_id": "0123456789abcdef0123456789abcdef",
            }),
            patch.object(main, "run_partner_evidence_agent", new=AsyncMock(return_value=(
                _proposal(), {
                    "agent_id": "full-shelf.partner-operations.v2",
                    "model_id": "gemini-3.5-flash",
                    "adk_framework": "google-adk/2.6.1",
                    "adk_session_id": "session", "adk_invocation_id": "invocation",
                    "adk_event_id": "event",
                },
            ))),
            patch.object(
                main,
                "execute_ledger_command",
                side_effect=httpx.HTTPStatusError(
                    "conflict", request=ledger_request, response=conflict
                ),
            ),
        ):
            response = client.post(
                "/api/v1/orchestrator/partner-evidence",
                headers={
                    "Authorization": "Bearer signed",
                    "traceparent": (
                        "00-0123456789abcdef0123456789abcdef-"
                        "0123456789abcdef-01"
                    ),
                },
                json=REQUEST,
            )
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["detail"] == "PARTNER_EVIDENCE_SOURCE_EVENT_CONFLICT"
