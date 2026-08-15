import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from full_shelf_domain.ledger_commands import (
    LedgerCommand,
    LedgerCommandType,
    OpenRecallIncidentPayload,
)


def make_command(**overrides):
    values = {
        "command_id": "CMD-AUDIT-001",
        "idempotency_key": "audit:recall:open:001",
        "tenant_id": "audit-tenant",
        "incident_id": "INC-ALT-777",
        "agent_role": "INCIDENT_COORDINATOR",
        "command_type": LedgerCommandType.OPEN_RECALL_INCIDENT,
        "expected_plan_revision": "rev42",
        "trace_id": "0123456789abcdef0123456789abcdef",
        "payload": {
            "incident_id": "INC-ALT-777",
            "coordinator_id": "COORD-ALT-777",
            "lot_id": "LOT-ALT-908",
            "source_event_id": "recall-message-alt",
            "source_publish_time": "2026-08-14T15:00:00Z",
            "model_armor_correlation_id": "0123456789abcdef0123456789abcdef",
            "details": {"hazard": "ALTERED_TEST_HAZARD", "cases": 13},
        },
    }
    values.update(overrides)
    return LedgerCommand.model_validate(values)


def test_command_validates_altered_noncanonical_payload():
    command = make_command()
    payload = command.validated_payload()
    assert isinstance(payload, OpenRecallIncidentPayload)
    assert payload.incident_id == "INC-ALT-777"
    assert payload.lot_id == "LOT-ALT-908"


def test_stable_receipt_id_is_deterministic_for_idempotency_key():
    first = make_command(command_id="CMD-FIRST")
    duplicate = make_command(command_id="CMD-REDELIVERY")
    assert first.stable_receipt_id() == duplicate.stable_receipt_id()


def test_receipt_id_is_tenant_scoped():
    assert make_command(tenant_id="tenant-a").stable_receipt_id() != make_command(
        tenant_id="tenant-b"
    ).stable_receipt_id()


def test_command_rejects_unknown_top_level_fields():
    with pytest.raises(ValidationError):
        make_command(untrusted_identity="attacker@example.com")


def test_command_rejects_unknown_payload_fields():
    command = make_command(
        payload={
            "incident_id": "INC-ALT-777",
            "coordinator_id": "COORD-ALT-777",
            "lot_id": "LOT-ALT-908",
            "source_event_id": "recall-message-alt",
            "source_publish_time": "2026-08-14T15:00:00Z",
            "model_armor_correlation_id": "0123456789abcdef0123456789abcdef",
            "details": {},
            "authoritative_status_override": "CLOSED",
        }
    )
    with pytest.raises(ValidationError):
        command.validated_payload()


def test_acknowledgment_hold_requires_positive_case_count():
    command = make_command(
        command_type=LedgerCommandType.RECORD_ACKNOWLEDGMENT_HOLD,
        payload={
            "incident_id": "INC-ALT-777",
            "hold_incident_id": "INC-ALT-777-HOLD-SITE-X",
            "coordinator_id": "COORD-ALT-777",
            "lot_id": "LOT-ALT-908",
            "site_id": "SITE-X",
            "unconfirmed_cases": 0,
            "task_name": "projects/test/locations/test/queues/test/tasks/test",
        },
    )
    with pytest.raises(ValidationError):
        command.validated_payload()


def test_checked_in_command_contract_matches_runtime_command_types():
    contract_path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "schemas"
        / "ledger_command.json"
    )
    contract = json.loads(contract_path.read_text())
    assert set(contract["properties"]["command_type"]["enum"]) == {
        command_type.value for command_type in LedgerCommandType
    }
    assert "incident_id" in contract["required"]
