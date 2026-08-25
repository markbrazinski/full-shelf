import json
from pathlib import Path

import jsonschema
import pytest
import yaml


CONTRACTS = Path(__file__).resolve().parents[1]


def _schema(name):
    return json.loads((CONTRACTS / "schemas" / name).read_text())


@pytest.mark.parametrize(
    "name",
    [
        "approval.json", "event.json", "incident.json", "plan.json",
        "ledger_command.json", "operating_day_request.json",
        "recurring_daily_request.json", "ledger_error.json",
        "partner_evidence_request.json",
        "partner_custody_confirmation_details.json",
    ],
)
def test_schema_is_valid_draft_2020_12(name):
    jsonschema.Draft202012Validator.check_schema(_schema(name))


def test_complete_approval_binding_accepts_both_actions_and_rejects_partial_diff():
    schema = _schema("approval.json")
    envelope = {
        "approval_id": "APP-1", "tenant_id": "tenant-a",
        "operating_day": "2026-08-14", "authority_scope": "tenant-a@2026-08-14",
        "rev_id": "rev08", "principal_id": "human-subject",
        "incident_id": "INC-TRUCK", "plan_id": "PLAN-1",
        "source_revision": "rev07", "proposed_revision": "rev08",
        "plan_diff": {
            "source_revision": "rev07", "proposed_revision": "rev08",
            "reroute_order_id": "ORDER-R", "reroute_cases": 17,
            "reroute_target_vehicle": "VEHICLE-B", "pickup_order_id": "ORDER-P",
            "pickup_cases": 8, "plan_diff_hash": "a" * 64,
        },
        "kms_key_version": "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1",
        "kms_signature": "c2lnbmF0dXJl", "expires_at": "2026-08-15T00:00:00Z",
    }
    jsonschema.validate(envelope, schema)

    del envelope["plan_diff"]["pickup_cases"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(envelope, schema)


def test_locked_incident_lifecycle_and_planning_events_are_contract_states():
    incident_states = _schema("incident.json")["properties"]["status"]["enum"]
    assert incident_states[:6] == [
        "DETECTED", "SCOPING", "CONTAINMENT_IN_PROGRESS",
        "PARTIALLY_CONTAINED", "CONTAINED", "CLOSED",
    ]
    event_types = set(_schema("event.json")["properties"]["event_type"]["enum"])
    assert {"PLAN_DAY_REQUESTED", "PLAN_NEXT_DAY_REQUESTED", "RECALL_NOTICE_RECEIVED"} <= event_types


def test_incident_contract_exposes_managed_model_armor_correlation():
    details = _schema("incident.json")["properties"]["details"]
    correlation = details["properties"]["model_armor_correlation_id"]

    assert correlation == {"type": "string", "pattern": "^[0-9a-f]{32}$"}


def test_operating_day_request_uses_product_identity_not_delivery_identity():
    schema = _schema("operating_day_request.json")
    assert set(schema["required"]) == {
        "event_type", "tenant_id", "operating_day", "operating_plan"
    }
    assert "qualification_profile" not in schema["properties"]
    assert "message_id" not in schema["properties"]


def test_recurring_daily_request_has_no_caller_selected_day_or_profile():
    schema = _schema("recurring_daily_request.json")
    assert set(schema["required"]) == {
        "event_type", "tenant_id", "operating_plan"
    }
    assert "operating_day" not in schema["properties"]
    assert "qualification_profile" not in schema["properties"]
    assert "timestamp" not in schema["properties"]


def test_next_day_request_has_only_ordinary_scope_and_event_type():
    schema = _schema("next_day_request.json")
    assert set(schema["required"]) == {"event_type", "tenant_id"}
    assert "qualification_profile" not in schema["properties"]
    assert "publish_time" not in schema["properties"]
    assert "message_id" not in schema["properties"]


def test_next_day_draft_requires_constraints_and_human_approval():
    schema = _schema("plan.json")
    draft = {
        "plan_id": "PLAN-TOMORROW", "tenant_id": "tenant-a", "revision": "rev01",
        "status": "DRAFT_WITH_CONSTRAINTS", "orders": [],
        "constraints": [{
            "constraint_type": "MOVEMENT_BARRIER", "subject_id": "LOT-1",
            "details": {}, "status": "ACTIVE",
        }],
        "human_approval_required": True, "created_at": "2026-08-15T00:00:00Z",
    }
    jsonschema.validate(draft, schema)
    draft["human_approval_required"] = False
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(draft, schema)


def test_ledger_collision_contract_is_permanent_and_zero_mutation():
    schema = _schema("ledger_error.json")
    rejection = {
        "code": "IDEMPOTENCY_KEY_COLLISION",
        "category": "PERMANENT_BUSINESS_REJECTION",
        "retryable": False,
        "mutations_applied": 0,
        "collision_kind": "BUSINESS_IDENTITY_ALREADY_EXISTS",
    }
    jsonschema.validate(rejection, schema)


def test_partner_evidence_ingress_is_constant_and_has_no_scope_overrides():
    schema = _schema("partner_evidence_request.json")
    body = {
        "event_type": "PARTNER_CUSTODY_EVIDENCE_RECEIVED",
        "source_event_id": "partner-event-1",
        "incident_id": "INC-2231",
        "original_text": "We pulled the remaining lettuce.",
        "source_occurred_at": "2026-08-14T10:15:00Z",
    }
    jsonschema.validate(body, schema)
    for forbidden in (
        "tenant_id", "partner_id", "site_id", "lot_id", "quantity",
        "work_item_id", "plan_revision", "operating_day",
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**body, forbidden: "caller-selected"}, schema)


def test_partner_custody_work_item_details_are_closed_and_all_required():
    schema = _schema("partner_custody_confirmation_details.json")
    details = {
        "schema_version": "partner-custody-confirmation.v1",
        "partner_id": "PARTNER-AGENCY-01", "site_id": "SITE-01",
        "custody_node_id": "N-ST01", "lot_id": "LTC-4471",
        "expected_cases": 8,
        "expected_acknowledgment_status": "UNCONFIRMED",
        "requested_acknowledgment_status": "CONFIRMED",
        "hold_incident_id": "HOLD-01", "operating_day": "2026-08-14",
        "source_task_name": "projects/p/locations/l/queues/q/tasks/t",
    }
    jsonschema.validate(details, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**details, "tenant_id": "caller-selected"}, schema)
    for required in schema["required"]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {key: value for key, value in details.items() if key != required}, schema
            )


def test_openapi_records_managed_and_retired_paths_truthfully():
    orchestrator = yaml.safe_load((CONTRACTS / "openapi" / "orchestrator.yaml").read_text())
    ledger = yaml.safe_load((CONTRACTS / "openapi" / "plan-ledger.yaml").read_text())

    assert "/api/v1/orchestrator/pubsub/push" in orchestrator["paths"]
    assert "/api/v1/orchestrator/recall/trigger" in orchestrator["paths"]
    assert orchestrator["paths"]["/api/v1/orchestrator/recall/execute-hero-loop"]["post"]["deprecated"]
    assert "/api/v1/approvals/approve-and-activate" in ledger["paths"]
    assert ledger["paths"]["/api/v1/actions/execute"]["post"]["responses"].keys() == {"410"}
