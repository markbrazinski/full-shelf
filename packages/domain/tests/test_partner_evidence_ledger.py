import copy
import json
from datetime import datetime, timezone

import pytest

from full_shelf_domain.identity import VerifiedGoogleIdentity
from full_shelf_domain.ledger_commands import LedgerCommand
from full_shelf_domain.ledger_executor import (
    IdempotencyKeyCollision,
    SpannerLedgerCommandExecutor,
)
from full_shelf_domain.partner_evidence import source_sha256


IDENTITY = VerifiedGoogleIdentity(
    subject="ledger-workload", email="ledger@example.com",
    audience="https://ledger", issuer="https://accounts.google.com",
    expires_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
)


DETAILS = {
    "schema_version": "partner-custody-confirmation.v1",
    "partner_id": "PARTNER-AGENCY-01", "site_id": "SITE-01",
    "custody_node_id": "N-ST01", "lot_id": "LTC-4471",
    "expected_cases": 8, "expected_acknowledgment_status": "UNCONFIRMED",
    "requested_acknowledgment_status": "CONFIRMED",
    "hold_incident_id": "HOLD-01", "operating_day": "2026-08-14",
    "source_task_name": "projects/p/locations/l/queues/q/tasks/t",
}


def candidate(complete):
    claims = {}
    if complete:
        claims = {
            "lot": {"value": "LTC-4471", "quote": "LTC-4471"},
            "quantity": {"value": 8, "quote": "8 cases"},
            "location": {"value": "Site 01", "quote": "Site 01"},
            "disposition": {"value": "ISOLATED_IN_QUARANTINE",
                            "quote": "ISOLATED_IN_QUARANTINE"},
            "confirmation_time": {"value": "10:18", "quote": "confirmed at 10:18"},
        }
    return {
        "incident_id": "INC-2231", "partner_id": "PARTNER-AGENCY-01",
        "site_id": "SITE-01", "custody_node_id": "N-ST01",
        "work_item_id": "WORK-PCF-01",
        "expected_acknowledgment_status": "UNCONFIRMED",
        "requested_acknowledgment_status": "CONFIRMED",
        "lot": None, "quantity": None, "location": None, "disposition": None,
        "confirmation_time": None, "requested_mutation": "CONFIRM_CUSTODY",
        "rationale": "Advisory interpretation only.", "confidence": 0.9,
        **claims,
    }


def command(complete=False, *, source_event_id="partner-event-1"):
    text = (
        "LTC-4471 · 8 cases · ISOLATED_IN_QUARANTINE at Site 01 · confirmed at 10:18."
        if complete else "We pulled the remaining lettuce. Should be all good."
    )
    return LedgerCommand.model_validate({
        "command_id": "CMD-PE-01", "idempotency_key": f"partner:{source_event_id}",
        "tenant_id": "audit-tenant", "incident_id": "INC-2231",
        "agent_role": "PARTNER_OPERATIONS_AGENT",
        "command_type": "PROCESS_PARTNER_EVIDENCE",
        "expected_plan_revision": "rev08",
        "trace_id": "0123456789abcdef0123456789abcdef",
        "payload": {
            "event_type": "PARTNER_CUSTODY_EVIDENCE_RECEIVED",
            "source_event_id": source_event_id, "operating_day": "2026-08-14",
            "source_occurred_at": "2026-08-14T10:18:00+00:00",
            "source_text": text, "source_sha256": source_sha256(text),
            "partner_id": "PARTNER-AGENCY-01", "callback_subject": "partner-sub",
            "callback_email": "partner@example.com", "callback_audience": "https://callback",
            "callback_issuer": "https://accounts.google.com",
            "callback_provenance": "AUTHENTICATED_PARTNER_CALLBACK",
            "model_armor": {"status": "APPROVED", "safety_verdict": "PASSED"},
            "proposal": candidate(complete),
            "agent_id": "full-shelf.partner-operations.v1",
            "model_id": "gemini-3.5-flash", "adk_framework": "google-adk/2.6.1",
            "adk_session_id": "session-real", "adk_invocation_id": "invocation-real",
            "adk_event_id": "event-real",
        },
    })


class Tx:
    def __init__(self, *, second_update=1, prior=None):
        self.second_update = second_update
        self.prior = prior
        self.inserts = []
        self.updates = []

    def execute_sql(self, sql, params, param_types):
        if "FROM Receipts" in sql:
            return []
        if "SELECT revision FROM PlanRevisions" in sql:
            return []
        if "SELECT status FROM PlanRevisions" in sql:
            return [("INVALIDATED_RECALL",)]
        if "FROM PartnerEvidenceEvents" in sql:
            return [self.prior] if self.prior else []
        if "FROM Incidents" in sql:
            return [("PARTIALLY_CONTAINED", "PARTIALLY_CONTAINED", "LTC-4471")]
        if "FROM WorkItems" in sql:
            return [("WORK-PCF-01", json.dumps(DETAILS))]
        if "FROM CustodyNodes" in sql:
            return [("Site 01", 8, "UNCONFIRMED")]
        if "FROM CustodyEdges" in sql:
            return [(8,)]
        raise AssertionError(sql)

    def execute_update(self, sql, params, param_types):
        self.updates.append((sql, copy.deepcopy(params)))
        if "UPDATE WorkItems" in sql:
            return self.second_update
        return 1

    def insert(self, table, columns, values):
        self.inserts.append({"table": table, "columns": columns, "values": values})


class DB:
    def __init__(self, tx):
        self.tx = tx

    def run_in_transaction(self, callback):
        before = (copy.deepcopy(self.tx.inserts), copy.deepcopy(self.tx.updates))
        try:
            return callback(self.tx)
        except Exception:
            self.tx.inserts, self.tx.updates = before
            raise


def execute(cmd, tx):
    return SpannerLedgerCommandExecutor(
        DB(tx), allowed_tenant_ids={"audit-tenant"}
    ).execute(cmd, IDENTITY)


def test_vague_path_inserts_evidence_and_exactly_one_denied_receipt():
    tx = Tx()
    result = execute(command(), tx)
    assert result.receipt["status"] == "DENIED"
    assert result.receipt["mutations_applied"] == 0
    assert result.receipt["evidence_mutations_applied"] == 1
    assert [row["table"] for row in tx.inserts] == ["PartnerEvidenceEvents", "Receipts"]
    evidence_receipt = tx.inserts[0]["values"][0][28]
    receipt_id = tx.inserts[1]["values"][0][1]
    assert evidence_receipt == receipt_id == command().stable_receipt_id()


def test_complete_path_updates_exactly_node_and_stored_work_item():
    tx = Tx()
    result = execute(command(True), tx)
    assert result.receipt["status"] == "SUCCESS"
    assert result.receipt["mutations_applied"] == 2
    assert len(tx.updates) == 2
    assert "UPDATE CustodyNodes" in tx.updates[0][0]
    assert "work_item_id=@work_item_id" in tx.updates[1][0]
    assert tx.updates[1][1]["work_item_id"] == "WORK-PCF-01"
    assert [row["table"] for row in tx.inserts] == ["PartnerEvidenceEvents", "Receipts"]


def test_second_update_failure_rolls_back_custody_evidence_and_receipt():
    tx = Tx(second_update=0)
    with pytest.raises(ValueError, match="WORK_ITEM_UPDATE_PRECONDITION_FAILED"):
        execute(command(True), tx)
    assert tx.updates == []
    assert tx.inserts == []


def test_conflicting_source_event_reuse_fails_before_any_write():
    prior = ("INC-OTHER", "PARTNER-AGENCY-01",
             datetime(2026, 8, 14, 10, 18, tzinfo=timezone.utc), "bad", "RCT-OLD")
    tx = Tx(prior=prior)
    with pytest.raises(IdempotencyKeyCollision):
        execute(command(), tx)
    assert tx.inserts == [] and tx.updates == []
