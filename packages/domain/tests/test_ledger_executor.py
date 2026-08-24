import json
from datetime import date, datetime, timezone

import pytest

from full_shelf_domain.identity import VerifiedGoogleIdentity
from full_shelf_domain.ledger_commands import LedgerCommand, LedgerCommandType
from full_shelf_domain.ledger_executor import (
    IdempotencyKeyCollision,
    SpannerLedgerCommandExecutor,
)
from full_shelf_domain.kms import compute_plan_diff_hash
from full_shelf_domain.models import PlanDiff


IDENTITY = VerifiedGoogleIdentity(
    subject="105774551577568412756",
    email="orchestrator@example.iam.gserviceaccount.com",
    audience="https://ledger.example.run.app",
    issuer="https://accounts.google.com",
    expires_at=datetime(2026, 8, 13, 22, 0, tzinfo=timezone.utc),
)


class FakeTransaction:
    def __init__(
        self,
        active_revision="rev42",
        existing_receipt=None,
        coordinator_children='["INC-TRUCK-ALT"]',
        source_orders=None,
        approval_rows=None,
    ):
        self.active_revision = active_revision
        self.existing_receipt = existing_receipt
        self.coordinator_children = coordinator_children
        self.source_orders = source_orders or []
        self.approval_rows = approval_rows or []
        self.inserts = []
        self.upserts = []
        self.updates = []

    def execute_sql(self, sql, params, param_types):
        if "idempotency_key" in sql:
            return [self.existing_receipt] if self.existing_receipt else []
        if "FROM PlanRevisions" in sql:
            return [(self.active_revision,)] if self.active_revision else []
        if "FROM Incidents" in sql:
            return []
        if "FROM Approvals" in sql:
            return self.approval_rows
        if "FROM Coordinators" in sql:
            return [(self.coordinator_children,)]
        if "FROM Orders" in sql:
            return self.source_orders
        if "FROM Vehicles" in sql:
            return [(60, 36, True)]
        raise AssertionError(f"Unexpected SQL: {sql}")

    def insert(self, **kwargs):
        self.inserts.append(kwargs)

    def insert_or_update(self, **kwargs):
        self.upserts.append(kwargs)

    def execute_update(self, sql, params, param_types):
        self.updates.append((sql, params, param_types))
        return 1


class FakeDatabase:
    def __init__(self, transaction):
        self.transaction = transaction
        self.calls = 0

    def run_in_transaction(self, callback):
        self.calls += 1
        return callback(self.transaction)


def coordinator_command(**overrides):
    values = {
        "command_id": "CMD-COORD-ALT-001",
        "idempotency_key": "alt:coord:waiting:001",
        "tenant_id": "audit-tenant",
        "incident_id": "INC-ALT-777",
        "agent_role": "INCIDENT_COORDINATOR",
        "command_type": LedgerCommandType.PERSIST_COORDINATOR,
        "expected_plan_revision": "rev42",
        "trace_id": "0123456789abcdef0123456789abcdef",
        "payload": {
            "coordinator_id": "COORD-ALT-001",
            "state": "WAITING_FOR_EVENTS",
            "checkpoint": "CHK-ALT-001",
            "active_plan_revision": "rev42",
            "child_incident_ids": [],
        },
    }
    values.update(overrides)
    return LedgerCommand.model_validate(values)


def test_successful_command_commits_state_and_receipt_atomically():
    transaction = FakeTransaction()
    result = SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(
        coordinator_command(), IDENTITY
    )
    assert result.receipt["status"] == "SUCCESS"
    assert result.additional_mutations == 1
    assert len(transaction.upserts) == 1
    assert [item["table"] for item in transaction.inserts] == ["Receipts"]


def test_unconfigured_tenant_is_rejected_before_transaction():
    transaction = FakeTransaction()
    database = FakeDatabase(transaction)
    try:
        SpannerLedgerCommandExecutor(
            database,
            allowed_tenant_ids={"different-tenant"},
        ).execute(coordinator_command(), IDENTITY)
    except PermissionError as exc:
        assert str(exc) == "TENANT_SCOPE_NOT_AUTHORIZED"
    else:
        raise AssertionError("Unconfigured tenant reached the transaction boundary")
    assert database.calls == 0
    assert transaction.inserts == []
    assert transaction.upserts == []


def test_stale_revision_writes_denial_receipt_but_no_plan_state():
    transaction = FakeTransaction(active_revision="rev41")
    result = SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(
        coordinator_command(), IDENTITY
    )
    assert result.receipt["status"] == "DENIED"
    assert result.additional_mutations == 0
    assert transaction.upserts == []
    assert [item["table"] for item in transaction.inserts] == ["Receipts"]


def test_unauthorized_logical_role_writes_only_denial_receipt():
    transaction = FakeTransaction()
    result = SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(
        coordinator_command(agent_role="PARTNER_OPERATIONS_AGENT"), IDENTITY
    )
    assert result.receipt["status"] == "DENIED"
    assert result.additional_mutations == 0
    assert transaction.upserts == []
    assert [item["table"] for item in transaction.inserts] == ["Receipts"]


def test_duplicate_returns_stable_receipt_and_zero_additional_mutations():
    timestamp = datetime(2026, 8, 13, 21, 30, tzinfo=timezone.utc)
    existing = (
        "RCT-STABLE",
        "CMD-FIRST",
        "rev42",
        "PERSIST_COORDINATOR",
        "SUCCESS",
        1,
        "PERSIST_COORDINATOR committed",
        "first-trace-id-0000000000000000",
        timestamp,
        IDENTITY.subject,
        IDENTITY.email,
        "INCIDENT_COORDINATOR",
        coordinator_command().request_fingerprint(),
    )
    transaction = FakeTransaction(existing_receipt=existing)
    result = SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(
        coordinator_command(command_id="CMD-REDELIVERED"), IDENTITY
    )
    assert result.idempotent_replay is True
    assert result.additional_mutations == 0
    assert result.receipt["receipt_id"] == "RCT-STABLE"
    assert transaction.inserts == []
    assert transaction.upserts == []


def test_daily_scheduler_command_atomically_initializes_isolated_operating_plan():
    class DailyTransaction(FakeTransaction):
        def __init__(self, *, existing_business_identity=False):
            super().__init__(active_revision=None)
            self.existing_business_identity = existing_business_identity

        def execute_sql(self, sql, params, param_types):
            if "idempotency_key" in sql:
                return []
            if "SELECT revision FROM PlanRevisions" in sql:
                return []
            if "AND plan_id = @plan_id" in sql:
                return [("SUPERSEDED",)] if self.existing_business_identity else []
            if "SELECT status FROM PlanRevisions" in sql:
                return []
            if "FROM Tenants" in sql:
                return []
            raise AssertionError(f"Unexpected SQL: {sql}")

    command = coordinator_command(
        command_id="CMD-DAY-ALT",
        idempotency_key="daily-plan:alt",
        tenant_id="audit-tenant-20260814",
        incident_id="INC-DAY-ALT",
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        command_type=LedgerCommandType.SAVE_PLAN_REVISION,
        expected_plan_revision="rev07",
        payload={
            "logical_tenant_id": "audit-tenant",
            "operating_day": "2026-08-14",
            "request_type": "PLAN_DAY_REQUESTED",
            "authority_scope": "audit-tenant@2026-08-14",
            "tenant_name": "Altered isolated operating day",
            "plan_id": "PLAN-ALT-DAY",
            "revision": "rev07",
            "status": "ACTIVE",
            "lots": [{
                "lot_id": "LOT-ALT", "code": "LOT-ALT",
                "produce_type": "Spinach", "hazard_status": "CLEAR_SAFE",
                "total_cases": 12,
            }],
            "vehicles": [{
                "vehicle_id": "VEHICLE-ALT", "name": "Vehicle Alt",
                "max_capacity_cases": 20, "current_load_cases": 12,
                "is_operational": True,
            }],
            "orders": [{
                "order_id": "ORDER-ALT", "destination_agency_id": "AGENCY-ALT",
                "destination_agency_name": "Agency Alt", "cases": 12,
                "lot_id": "LOT-ALT", "assigned_vehicle_id": "VEHICLE-ALT",
                "status": "SCHEDULED",
            }],
            "custody_nodes": [
                {"node_id": "NODE-WH", "node_type": "WAREHOUSE",
                 "name": "Warehouse", "on_hand_cases": 5,
                 "acknowledgment_status": "CONFIRMED"},
                {"node_id": "NODE-AGENCY", "node_type": "AGENCY",
                 "name": "Agency", "on_hand_cases": 7,
                 "acknowledgment_status": "CONFIRMED"},
            ],
            "custody_edges": [{
                "edge_id": "EDGE-1", "source_node_id": "NODE-WH",
                "target_node_id": "NODE-AGENCY", "lot_id": "LOT-ALT",
                "case_count": 7, "is_sub_distribution": False,
            }],
        },
    )
    transaction = DailyTransaction()
    result = SpannerLedgerCommandExecutor(
        FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant-20260814"}
    ).execute(command, IDENTITY)

    assert result.receipt["status"] == "SUCCESS"
    assert result.additional_mutations == 9
    assert [item["table"] for item in transaction.inserts] == [
        "Tenants", "PlanRevisions", "Lots", "Vehicles", "Orders",
        "CustodyNodes", "CustodyEdges", "InboundEvents", "Receipts",
    ]
    assert transaction.updates == []

    collision = DailyTransaction(existing_business_identity=True)
    with pytest.raises(IdempotencyKeyCollision) as exc:
        SpannerLedgerCommandExecutor(
            FakeDatabase(collision),
            allowed_tenant_ids={"audit-tenant-20260814"},
        ).execute(command, IDENTITY)
    assert exc.value.code == "IDEMPOTENCY_KEY_COLLISION"
    assert exc.value.collision_kind == "BUSINESS_IDENTITY_ALREADY_EXISTS"
    assert collision.inserts == []
    assert collision.upserts == []
    assert collision.updates == []


def test_open_recall_preserves_existing_coordinator_child_incident():
    command = coordinator_command(
        command_id="CMD-OPEN-ALT",
        idempotency_key="alt:open-recall",
        incident_id="INC-RECALL-ALT",
        command_type=LedgerCommandType.OPEN_RECALL_INCIDENT,
        payload={
            "incident_id": "INC-RECALL-ALT",
            "coordinator_id": "COORD-ALT-001",
            "lot_id": "LOT-ALT-908",
            "source_event_id": "recall-message-alt",
            "source_publish_time": "2026-08-14T15:00:00Z",
            "model_armor_correlation_id": "0123456789abcdef0123456789abcdef",
            "details": {"hazard": "ALTERED_TEST_HAZARD"},
        },
    )
    transaction = FakeTransaction()
    result = SpannerLedgerCommandExecutor(
        FakeDatabase(transaction),
        allowed_tenant_ids={"audit-tenant"},
    ).execute(command, IDENTITY)
    assert result.additional_mutations == 3
    assert [item["table"] for item in transaction.inserts] == [
        "Incidents", "InboundEvents", "Receipts"
    ]
    assert transaction.updates[0][1]["children"] == (
        '["INC-TRUCK-ALT","INC-RECALL-ALT"]'
    )
    persisted_details = json.loads(transaction.inserts[0]["values"][0][7])
    assert persisted_details["model_armor_correlation_id"] == command.trace_id


def test_open_recall_rejects_model_armor_correlation_substitution_before_mutation():
    command = coordinator_command(
        command_id="CMD-OPEN-CORRELATION-MISMATCH",
        idempotency_key="alt:open-recall:correlation-mismatch",
        incident_id="INC-RECALL-ALT",
        command_type=LedgerCommandType.OPEN_RECALL_INCIDENT,
        payload={
            "incident_id": "INC-RECALL-ALT",
            "coordinator_id": "COORD-ALT-001",
            "lot_id": "LOT-ALT-908",
            "source_event_id": "recall-message-alt",
            "source_publish_time": "2026-08-14T15:00:00Z",
            "model_armor_correlation_id": "abcdef0123456789abcdef0123456789",
            "details": {"hazard": "ALTERED_TEST_HAZARD"},
        },
    )
    transaction = FakeTransaction()

    with pytest.raises(ValueError, match="MODEL_ARMOR_CORRELATION_MISMATCH"):
        SpannerLedgerCommandExecutor(
            FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
        ).execute(command, IDENTITY)

    assert transaction.inserts == []
    assert transaction.upserts == []
    assert transaction.updates == []


def test_next_day_draft_atomically_persists_event_constraints_plan_and_coordinator():
    class ContinuityTransaction(FakeTransaction):
        def execute_sql(self, sql, params, param_types):
            if "idempotency_key" in sql:
                return []
            if "AND plan_id = @plan_id" in sql:
                return []
            if "SELECT status FROM PlanRevisions" in sql:
                return [("INVALIDATED_RECALL",)]
            if "SELECT revision FROM PlanRevisions" in sql:
                return []
            if "FROM MovementBarriers" in sql:
                return [("BARRIER-ALT",)]
            if "FROM RecoveryShortfalls" in sql:
                return [("SHORT-ALT",)]
            if "incident_type = 'DEADLINE_HOLD'" in sql:
                return [('{"site_id":"SITE-X","unconfirmed_cases":3}',)]
            raise AssertionError(f"Unexpected SQL: {sql}")

    command = coordinator_command(
        command_id="CMD-NEXT-ALT",
        idempotency_key="audit:PLAN-ALT-NEXT:rev01:day-close",
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        command_type=LedgerCommandType.CREATE_NEXT_DAY_DRAFT,
        payload={
            "source_event_id": "message-alt-1",
            "source_operating_day": "2026-08-13",
            "event_type": "PLAN_NEXT_DAY_REQUESTED",
            "operating_date": "2026-08-14",
            "plan_id": "PLAN-ALT-NEXT",
            "revision": "rev01",
            "status": "DRAFT_WITH_CONSTRAINTS",
            "coordinator_id": "COORD-ALT-NEXT",
            "barriers": [{"barrier_id": "BARRIER-ALT", "lot_id": "LOT-ALT-908"}],
            "shortfalls": [{"shortfall_id": "SHORT-ALT", "agency_id": "AG-X",
                            "cases": 9}],
            "acknowledgment_holds": [{"hold_incident_id": "HOLD-ALT",
                                       "site_id": "SITE-X", "unconfirmed_cases": 3}],
            "human_approval_required": True,
        },
    )
    transaction = ContinuityTransaction()
    result = SpannerLedgerCommandExecutor(
        FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
    ).execute(command, IDENTITY)
    assert result.additional_mutations == 6
    assert [item["table"] for item in transaction.inserts] == [
        "PlanRevisions", "PlanConstraints", "InboundEvents", "Receipts"
    ]
    assert transaction.upserts[0]["table"] == "Coordinators"
    assert transaction.upserts[0]["values"][0][2:5] == [
        "DRAFT_WITH_CONSTRAINTS", "HUMAN_APPROVAL_REQUIRED", "rev01"
    ]


def test_legacy_next_day_receipt_replays_only_when_authoritative_draft_matches():
    timestamp = datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc)
    existing = (
        "RCT-NEXT-STABLE", "CMD-NEXT-DAY-2026-08-15-REV01", "rev01",
        "CREATE_NEXT_DAY_DRAFT", "SUCCESS", 6,
        "CREATE_NEXT_DAY_DRAFT committed", "legacy-trace-00000000000000000000",
        timestamp, IDENTITY.subject, IDENTITY.email,
        "FULFILLMENT_RECOVERY_PLANNER", "legacy-transport-bound-fingerprint",
    )

    class LegacyReplayTransaction(FakeTransaction):
        def execute_sql(self, sql, params, param_types):
            if "idempotency_key" in sql:
                return [existing]
            if "SELECT status FROM PlanRevisions" in sql:
                return [("DRAFT_WITH_CONSTRAINTS",)]
            if "FROM PlanConstraints" in sql:
                return [
                    ("LOT_MOVEMENT_BARRIER", "LOT-ALT-908",
                     json.dumps({"barrier_id": "BARRIER-ALT", "status": "ACTIVE"},
                                sort_keys=True), 1),
                    ("RECOVERY_PRIORITY", "AG-X",
                     json.dumps({"shortfall_id": "SHORT-ALT", "cases": 9,
                                 "status": "OPEN"}, sort_keys=True), 2),
                    ("ACKNOWLEDGMENT_HOLD", "SITE-X",
                     json.dumps({"hold_incident_id": "HOLD-ALT",
                                 "unconfirmed_cases": 3,
                                 "status": "ACKNOWLEDGMENT_HOLD_ACTIVE"},
                                sort_keys=True), 3),
                ]
            if "FROM Coordinators" in sql:
                return [("DRAFT_WITH_CONSTRAINTS", "HUMAN_APPROVAL_REQUIRED", "rev01")]
            raise AssertionError(f"Unexpected SQL: {sql}")

    command = coordinator_command(
        command_id="CMD-NEXT-DAY-2026-08-15-REV01",
        idempotency_key="audit-tenant:PLAN-2026-08-15:rev01:day-close",
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        command_type=LedgerCommandType.CREATE_NEXT_DAY_DRAFT,
        expected_plan_revision="rev08",
        payload={
            "source_event_id": "NEXTDAY-STABLE",
            "source_operating_day": "2026-08-14",
            "event_type": "PLAN_NEXT_DAY_REQUESTED",
            "operating_date": "2026-08-15",
            "plan_id": "PLAN-2026-08-15",
            "revision": "rev01",
            "status": "DRAFT_WITH_CONSTRAINTS",
            "coordinator_id": "COORD-2026-08-15",
            "barriers": [{"barrier_id": "BARRIER-ALT", "lot_id": "LOT-ALT-908"}],
            "shortfalls": [{"shortfall_id": "SHORT-ALT", "agency_id": "AG-X",
                            "cases": 9}],
            "acknowledgment_holds": [{"hold_incident_id": "HOLD-ALT",
                                       "site_id": "SITE-X", "unconfirmed_cases": 3}],
            "human_approval_required": True,
        },
    )
    transaction = LegacyReplayTransaction(existing_receipt=existing)
    result = SpannerLedgerCommandExecutor(
        FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
    ).execute(command, IDENTITY)
    assert result.idempotent_replay is True
    assert result.additional_mutations == 0
    assert result.receipt["receipt_id"] == "RCT-NEXT-STABLE"
    assert transaction.inserts == []


def test_unsigned_repair_command_is_not_a_valid_command_contract():
    with pytest.raises(ValueError):
        coordinator_command(
            command_type="APPLY_REPAIR_PLAN",
            agent_role="FULFILLMENT_RECOVERY_PLANNER",
            payload={"plan_id": "PLAN-ALT", "source_revision": "rev42",
                     "proposed_revision": "rev43", "orders": []},
        )


def _signed_diff():
    diff = PlanDiff(
        source_revision="rev42",
        proposed_revision="rev43",
        reroute_order_id="ORDER-REROUTE",
        reroute_cases=22,
        reroute_target_vehicle="VEHICLE-RECOVERY",
        pickup_order_id="ORDER-PICKUP",
        pickup_cases=20,
        plan_diff_hash="",
    )
    diff.plan_diff_hash = compute_plan_diff_hash(diff)
    return diff


def test_repair_approval_commits_before_any_plan_activation():
    diff = _signed_diff()
    command = coordinator_command(
        command_type=LedgerCommandType.PERSIST_REPAIR_APPROVAL,
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        payload={"plan_id": "PLAN-ALT", "source_revision": "rev42",
                 "proposed_revision": "rev43", "approval_id": "APP-ALT",
                 "operating_day": "2026-08-14",
                 "authority_scope": "audit-tenant@2026-08-14",
                 "approver_subject": "operator-sub", "approver_email": "operator@example.com",
                 "oauth_audience": "client.apps.googleusercontent.com",
                 "plan_diff_hash": diff.plan_diff_hash,
                 "kms_key_version": "projects/p/keys/k/versions/1",
                 "kms_signature": "signature", "expires_at": "2099-01-01T00:00:00Z",
                 "plan_diff": {
                     "reroute_order_id": diff.reroute_order_id,
                     "reroute_cases": diff.reroute_cases,
                     "reroute_target_vehicle": diff.reroute_target_vehicle,
                     "pickup_order_id": diff.pickup_order_id,
                     "pickup_cases": diff.pickup_cases,
                 }},
    )
    transaction = FakeTransaction()
    result = SpannerLedgerCommandExecutor(
        FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
    ).execute(command, IDENTITY)

    assert result.additional_mutations == 1
    assert [item["table"] for item in transaction.inserts] == ["Approvals", "Receipts"]
    assert transaction.updates == []
    assert json.loads(transaction.inserts[0]["values"][0][12]) == command.payload["plan_diff"]


def test_changed_signed_envelope_reusing_idempotency_key_is_rejected():
    diff = _signed_diff()
    base = coordinator_command(
        command_type=LedgerCommandType.PERSIST_REPAIR_APPROVAL,
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        payload={
            "operating_day": "2026-08-14",
            "authority_scope": "audit-tenant@2026-08-14",
            "plan_id": "PLAN-ALT", "source_revision": "rev42",
            "proposed_revision": "rev43", "approval_id": "APP-ALT",
            "approver_subject": "operator-sub",
            "approver_email": "operator@example.com",
            "oauth_audience": "client.apps.googleusercontent.com",
            "plan_diff_hash": diff.plan_diff_hash,
            "kms_key_version": "projects/p/keys/k/versions/1",
            "kms_signature": "signature",
            "expires_at": "2099-01-01T00:00:00Z",
            "plan_diff": {
                "reroute_order_id": diff.reroute_order_id,
                "reroute_cases": diff.reroute_cases,
                "reroute_target_vehicle": diff.reroute_target_vehicle,
                "pickup_order_id": diff.pickup_order_id,
                "pickup_cases": diff.pickup_cases,
            },
        },
    )
    existing = (
        "RCT-STABLE", base.command_id, "rev43", "PERSIST_REPAIR_APPROVAL",
        "SUCCESS", 1, "PERSIST_REPAIR_APPROVAL committed",
        base.trace_id, datetime(2026, 8, 14, tzinfo=timezone.utc),
        IDENTITY.subject, IDENTITY.email, base.agent_role,
        base.request_fingerprint(),
    )
    changed = base.model_copy(deep=True)
    changed.payload["expires_at"] = "2099-01-02T00:00:00Z"
    transaction = FakeTransaction(existing_receipt=existing)

    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_COLLISION"):
        SpannerLedgerCommandExecutor(
            FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
        ).execute(changed, IDENTITY)

    assert transaction.inserts == []
    assert transaction.updates == []


def test_separate_activation_reads_persisted_approval_and_derives_only_signed_changes():
    diff = _signed_diff()
    command = coordinator_command(
        command_id="CMD-APPROVED-ACTIVATION",
        idempotency_key="alt:approval:activate",
        command_type=LedgerCommandType.ACTIVATE_APPROVED_REPAIR_PLAN,
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        payload={"plan_id": "PLAN-ALT", "source_revision": "rev42",
                 "proposed_revision": "rev43", "approval_id": "APP-ALT",
                 "operating_day": "2026-08-14",
                 "authority_scope": "audit-tenant@2026-08-14"},
    )
    source = [
        ("O201", "AG1", "Agency 1", 18, "LOT-X", "TRUCK-01", "PLANNED"),
        ("ORDER-REROUTE", "AG2", "Agency 2", 22, "LOT-X", "TRUCK-01", "PLANNED"),
        ("ORDER-PICKUP", "AG3", "Agency 3", 20, "LOT-X", "TRUCK-01", "PLANNED"),
    ]
    plan_diff_json = json.dumps({
        "reroute_order_id": diff.reroute_order_id,
        "reroute_cases": diff.reroute_cases,
        "reroute_target_vehicle": diff.reroute_target_vehicle,
        "pickup_order_id": diff.pickup_order_id,
        "pickup_cases": diff.pickup_cases,
    }, sort_keys=True, separators=(",", ":"))
    transaction = FakeTransaction(
        source_orders=source,
        approval_rows=[(
            "INC-ALT-777", "PLAN-ALT", date(2026, 8, 14),
            "audit-tenant@2026-08-14", "rev42", "rev43",
            diff.plan_diff_hash, plan_diff_json,
            datetime(2099, 1, 1, tzinfo=timezone.utc),
        )],
    )
    result = SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(command, IDENTITY)
    assert result.additional_mutations == 2
    assert [item["table"] for item in transaction.inserts] == ["PlanRevisions", "Orders", "Receipts"]
    inserted = transaction.inserts[1]["values"]
    assert inserted[0][-2:] == ["TRUCK-01", "PLANNED"]
    assert inserted[1][-2:] == ["VEHICLE-RECOVERY", "REROUTED"]
    assert inserted[2][-2:] == [None, "PARTNER_PICKUP_CONVERTED"]


def test_incident_status_command_refuses_skipped_lifecycle_transition():
    command = coordinator_command(
        command_type=LedgerCommandType.SET_INCIDENT_STATUS,
        payload={
            "incident_id": "INC-ALT-777",
            "expected_status": "DETECTED",
            "new_status": "PARTIALLY_CONTAINED",
            "terminal_state": "PARTIALLY_CONTAINED",
        },
    )
    transaction = FakeTransaction()
    try:
        SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(command, IDENTITY)
    except ValueError as exc:
        assert str(exc) == "INCIDENT_LIFECYCLE_TRANSITION_DENIED"
    else:
        raise AssertionError("Skipped recall lifecycle transition was accepted")
    assert transaction.updates == []
    assert transaction.inserts == []


def test_incident_status_command_blocks_containment_without_zero_unconfirmed_cases():
    command = coordinator_command(
        command_type=LedgerCommandType.SET_INCIDENT_STATUS,
        payload={
            "incident_id": "INC-ALT-777",
            "expected_status": "PARTIALLY_CONTAINED",
            "new_status": "CONTAINED",
            "terminal_state": "CONTAINED",
            "unconfirmed_cases": 4,
        },
    )
    transaction = FakeTransaction()
    try:
        SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(command, IDENTITY)
    except ValueError as exc:
        assert str(exc) == "UNCONFIRMED_CASES_BLOCK_CONTAINMENT"
    else:
        raise AssertionError("Containment was accepted with unconfirmed cases")
    assert transaction.updates == []
    assert transaction.inserts == []


def test_incident_scope_mismatch_aborts_without_receipt_or_state_mutation():
    command = coordinator_command(
        incident_id="INC-SCOPED",
        command_type=LedgerCommandType.SET_INCIDENT_STATUS,
        payload={
            "incident_id": "INC-DIFFERENT",
            "expected_status": "DETECTED",
            "new_status": "SCOPING",
            "terminal_state": "NONE",
        },
    )
    transaction = FakeTransaction()
    try:
        SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(command, IDENTITY)
    except ValueError as exc:
        assert str(exc) == "INCIDENT_SCOPE_MISMATCH"
    else:
        raise AssertionError("Cross-incident command was accepted")
    assert transaction.updates == []
    assert transaction.inserts == []


# ---------------------------------------------------------------------------
# Candidate next-day assignments persisted as child Orders of the draft.
# ---------------------------------------------------------------------------

def _candidate_transaction():
    """Authoritative state a candidate schedule is validated against."""

    class CandidateTransaction(FakeTransaction):
        def execute_sql(self, sql, params, param_types):
            if "idempotency_key" in sql:
                return []
            if "AND plan_id = @plan_id" in sql:
                return []
            if "SELECT status FROM PlanRevisions" in sql:
                return [("INVALIDATED_RECALL",)]
            if "SELECT revision FROM PlanRevisions" in sql:
                return []
            if "FROM MovementBarriers" in sql:
                return [("BARRIER-ALT",)]
            if "FROM RecoveryShortfalls" in sql:
                return [("SHORT-ALT",)]
            if "incident_type = 'DEADLINE_HOLD'" in sql:
                return [('{"site_id":"SITE-X","unconfirmed_cases":3}',)]
            if "FROM Lots" in sql:
                return [("LOT-SAFE-ALT", 30)]
            if "FROM Vehicles" in sql:
                return [("VEHICLE-ALT", 40, 11)]
            raise AssertionError(f"Unexpected SQL: {sql}")

    return CandidateTransaction()


def _candidate_payload(**overrides):
    stop = {
        "order_id": "CAND-PLAN-ALT-NEXT-SHORT-ALT",
        "agency_id": "AG-X", "agency_name": "Altered Agency X",
        "cases": 9, "lot_id": "LOT-SAFE-ALT", "vehicle_id": "VEHICLE-ALT",
        "sequence": 1, "shortfall_id": "SHORT-ALT", "status": "CANDIDATE",
    }
    stop.update(overrides.pop("stop", {}))
    vehicle = {
        "vehicle_id": "VEHICLE-ALT", "capacity_cases": 40,
        "committed_load_cases": 11, "candidate_load_cases": 9, "stops": [stop],
    }
    vehicle.update(overrides.pop("vehicle", {}))
    payload = {
        "source_event_id": "message-alt-1",
        "source_operating_day": "2026-08-13",
        "event_type": "PLAN_NEXT_DAY_REQUESTED",
        "operating_date": "2026-08-14",
        "plan_id": "PLAN-2026-08-14",
        "revision": "rev01",
        "status": "DRAFT_WITH_CONSTRAINTS",
        "coordinator_id": "COORD-ALT-NEXT",
        "barriers": [{"barrier_id": "BARRIER-ALT", "lot_id": "LOT-ALT-908"}],
        "shortfalls": [{"shortfall_id": "SHORT-ALT", "agency_id": "AG-X",
                        "cases": 9}],
        "acknowledgment_holds": [{"hold_incident_id": "HOLD-ALT",
                                  "site_id": "SITE-X", "unconfirmed_cases": 3}],
        "human_approval_required": True,
        "candidate_vehicles": [vehicle],
        "unassigned_demand": [],
    }
    payload.update(overrides)
    return payload


def _candidate_command(**overrides):
    return coordinator_command(
        command_id="CMD-NEXT-CAND",
        idempotency_key="audit:PLAN-2026-08-14:rev01:day-close",
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        command_type=LedgerCommandType.CREATE_NEXT_DAY_DRAFT,
        payload=_candidate_payload(**overrides),
    )


def _execute_candidate(transaction, **overrides):
    return SpannerLedgerCommandExecutor(
        FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
    ).execute(_candidate_command(**overrides), IDENTITY)


def test_candidate_assignments_persist_as_child_orders_of_the_draft():
    """The exact generated assignments are stored, not re-derived on read."""
    transaction = _candidate_transaction()
    _execute_candidate(transaction)

    orders = [item for item in transaction.inserts if item["table"] == "Orders"]
    assert len(orders) == 1
    row = orders[0]["values"][0]
    # Subordinate to the draft revision: Orders interleaves in PlanRevisions.
    assert row[1:4] == ["PLAN-2026-08-14", "rev01", "CAND-PLAN-ALT-NEXT-SHORT-ALT"]
    assert row[6] == 9 and row[7] == "LOT-SAFE-ALT" and row[8] == "VEHICLE-ALT"
    # Never an activatable state.
    assert row[9] == "CANDIDATE"


def test_candidate_rows_never_claim_an_active_status():
    transaction = _candidate_transaction()
    _execute_candidate(transaction)
    for item in transaction.inserts:
        for row in item["values"]:
            assert "ACTIVE" not in [str(value) for value in row]


def test_unassigned_demand_persists_as_a_visible_draft_constraint():
    """Agency 03's carried shortfall must stay explicitly open."""
    transaction = _candidate_transaction()
    _execute_candidate(transaction, unassigned_demand=[
        {"shortfall_id": "SHORT-OPEN", "agency_id": "AG-SHORT", "cases": 20,
         "reason": "NO_CONFIRMED_SAFE_LOT_WITH_SUFFICIENT_CASES"}])
    constraints = [item for item in transaction.inserts
                   if item["table"] == "PlanConstraints"]
    unassigned = [row for item in constraints for row in item["values"]
                  if row[3] == "UNASSIGNED_DEMAND"]
    assert len(unassigned) == 1
    details = json.loads(unassigned[0][5])
    assert details["cases"] == 20 and details["agency_id"] == "AG-SHORT"


def test_recalled_lot_under_barrier_cannot_enter_the_candidate_plan():
    """A barred lot fails closed with no partial write."""
    transaction = _candidate_transaction()
    with pytest.raises(ValueError, match="CANDIDATE_LOT_UNDER_MOVEMENT_BARRIER"):
        _execute_candidate(transaction, stop={"lot_id": "LOT-ALT-908"})
    assert transaction.inserts == []
    assert transaction.upserts == []
    assert transaction.updates == []


def test_unsafe_lot_cannot_enter_the_candidate_plan():
    transaction = _candidate_transaction()
    with pytest.raises(ValueError, match="CANDIDATE_LOT_NOT_CONFIRMED_SAFE"):
        _execute_candidate(transaction, stop={"lot_id": "LOT-NOT-CLEARED"})
    assert transaction.inserts == []


def test_candidate_load_may_not_exceed_authoritative_vehicle_capacity():
    """40 capacity, 11 committed: a 30-case candidate overruns it."""
    transaction = _candidate_transaction()
    with pytest.raises(ValueError, match="CANDIDATE_LOAD_EXCEEDS_VEHICLE_CAPACITY"):
        _execute_candidate(
            transaction,
            shortfalls=[{"shortfall_id": "SHORT-ALT", "agency_id": "AG-X",
                         "cases": 30}],
            vehicle={"candidate_load_cases": 30},
            stop={"cases": 30},
        )
    assert transaction.inserts == []


def test_candidate_vehicle_must_be_operational_and_current():
    transaction = _candidate_transaction()
    with pytest.raises(ValueError, match="CANDIDATE_VEHICLE_NOT_OPERATIONAL"):
        _execute_candidate(transaction,
                           vehicle={"vehicle_id": "VEHICLE-GHOST"},
                           stop={"vehicle_id": "VEHICLE-GHOST"})
    assert transaction.inserts == []

    stale = _candidate_transaction()
    with pytest.raises(ValueError, match="CANDIDATE_VEHICLE_STATE_STALE"):
        _execute_candidate(stale, vehicle={"committed_load_cases": 0})
    assert stale.inserts == []


def test_candidate_stop_requires_an_open_shortfall_of_matching_size():
    transaction = _candidate_transaction()
    with pytest.raises(ValueError, match="CANDIDATE_STOP_WITHOUT_OPEN_SHORTFALL"):
        _execute_candidate(transaction, stop={"shortfall_id": "SHORT-GHOST"})
    assert transaction.inserts == []

    mismatched = _candidate_transaction()
    with pytest.raises(ValueError, match="CANDIDATE_CASES_DO_NOT_MATCH_SHORTFALL"):
        _execute_candidate(mismatched,
                           vehicle={"candidate_load_cases": 4},
                           stop={"cases": 4})
    assert mismatched.inserts == []


def test_candidate_draw_may_not_exceed_confirmed_safe_stock():
    """Two stops drawing 16 each exceed the lot's 30 confirmed-safe cases.

    The vehicle has ample room (200 capacity, 0 committed) so capacity is not
    the binding limit, which proves the stock check rather than the load check.
    """

    class RoomyTransaction(type(_candidate_transaction())):
        def execute_sql(self, sql, params, param_types):
            if "FROM Vehicles" in sql:
                return [("VEHICLE-ALT", 200, 0)]
            return super().execute_sql(sql, params, param_types)

    transaction = RoomyTransaction()
    with pytest.raises(ValueError, match="CANDIDATE_DRAW_EXCEEDS_CONFIRMED_SAFE_STOCK"):
        _execute_candidate(
            transaction,
            shortfalls=[{"shortfall_id": "SHORT-ALT", "agency_id": "AG-X",
                         "cases": 16},
                        {"shortfall_id": "SHORT-TWO", "agency_id": "AG-Y",
                         "cases": 15}],
            vehicle={"capacity_cases": 200, "committed_load_cases": 0,
                     "candidate_load_cases": 31, "stops": [
                {"order_id": "CAND-1", "agency_id": "AG-X", "agency_name": "X",
                 "cases": 16, "lot_id": "LOT-SAFE-ALT", "vehicle_id": "VEHICLE-ALT",
                 "sequence": 1, "shortfall_id": "SHORT-ALT", "status": "CANDIDATE"},
                {"order_id": "CAND-2", "agency_id": "AG-Y", "agency_name": "Y",
                 "cases": 15, "lot_id": "LOT-SAFE-ALT", "vehicle_id": "VEHICLE-ALT",
                 "sequence": 2, "shortfall_id": "SHORT-TWO", "status": "CANDIDATE"}]},
        )
    assert transaction.inserts == []


def test_candidate_plan_identity_must_match_its_operating_date():
    transaction = _candidate_transaction()
    with pytest.raises(ValueError, match="CANDIDATE_PLAN_IDENTITY_MISMATCH"):
        _execute_candidate(transaction, plan_id="PLAN-SOMEBODY-ELSE")
    assert transaction.inserts == []


def test_constraints_only_next_day_draft_still_commits_without_candidates():
    """The pre-existing caller contract is unchanged."""
    transaction = _candidate_transaction()
    result = _execute_candidate(transaction, candidate_vehicles=[])
    assert [item["table"] for item in transaction.inserts] == [
        "PlanRevisions", "PlanConstraints", "InboundEvents", "Receipts"
    ]
    assert result.additional_mutations == 6


def test_recommitting_the_same_candidate_draft_is_idempotent():
    """Requirement 6: a redelivered command writes nothing further.

    Order ids are derived from the draft plan and the shortfall they serve, so
    the regenerated command carries the same fingerprint and replays instead of
    inserting a second set of candidate rows.
    """
    command = _candidate_command()
    timestamp = datetime(2026, 8, 14, 17, 0, tzinfo=timezone.utc)
    existing = (
        "RCT-CAND-STABLE", command.command_id, "rev01",
        "CREATE_NEXT_DAY_DRAFT", "SUCCESS", 8,
        "CREATE_NEXT_DAY_DRAFT committed", "0123456789abcdef0123456789abcdef",
        timestamp, IDENTITY.subject, IDENTITY.email,
        "FULFILLMENT_RECOVERY_PLANNER", command.request_fingerprint(),
    )

    class ReplayTransaction(type(_candidate_transaction())):
        def execute_sql(self, sql, params, param_types):
            if "idempotency_key" in sql:
                return [existing]
            return super().execute_sql(sql, params, param_types)

    transaction = ReplayTransaction()
    result = SpannerLedgerCommandExecutor(
        FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
    ).execute(command, IDENTITY)

    assert result.idempotent_replay is True
    assert result.additional_mutations == 0
    assert result.receipt["receipt_id"] == "RCT-CAND-STABLE"
    assert transaction.inserts == []
    assert transaction.upserts == []


def test_candidate_order_ids_are_deterministic_across_regeneration():
    """The same authoritative state derives the same ids, twice."""
    first = _candidate_command().request_fingerprint()
    second = _candidate_command().request_fingerprint()
    assert first == second


# ---------------------------------------------------------------------------
# Repair proposal: what the agents propose, never what anyone authorized.
# ---------------------------------------------------------------------------

def _proposal_transaction(active="rev07", statuses=None):
    """Authoritative state a repair proposal is validated against."""
    known = statuses if statuses is not None else {"rev07": "ACTIVE"}

    class ProposalTransaction(FakeTransaction):
        def __init__(self):
            super().__init__(active_revision=active)

        def execute_sql(self, sql, params, param_types):
            if "idempotency_key" in sql:
                return []
            if "SELECT status FROM PlanRevisions" in sql:
                status = known.get(params.get("revision"))
                return [(status,)] if status else []
            if "FROM PlanRevisions" in sql:
                return [(self.active_revision,)] if self.active_revision else []
            raise AssertionError(f"Unexpected SQL: {sql}")

    return ProposalTransaction()


def _proposal_payload(**overrides):
    diff = {
        "reroute_order_id": "O202", "reroute_cases": 22,
        "reroute_target_vehicle": "TRUCK-02",
        "pickup_order_id": "O203", "pickup_cases": 20,
    }
    diff.update(overrides.pop("plan_diff", {}))
    payload = {
        "proposal_id": "PROP-ALT-1",
        "source_event_id": "telematics-evt-alt-1",
        "plan_id": "PLAN-ALT",
        "source_revision": "rev07",
        "proposed_revision": "rev08",
        "vehicle_id": "TRUCK-01",
        "absorbing_vehicle_capacity_cases": 60,
        "absorbing_vehicle_committed_cases": 36,
        "plan_diff": diff,
    }
    payload.update(overrides)
    return payload


def _proposal_command(**overrides):
    return coordinator_command(
        command_id="CMD-PROPOSAL-ALT",
        idempotency_key="audit:PLAN-ALT:rev07:repair-proposal",
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        command_type=LedgerCommandType.PERSIST_REPAIR_PROPOSAL,
        expected_plan_revision="rev07",
        payload=_proposal_payload(**overrides),
    )


def _execute_proposal(transaction, **overrides):
    return SpannerLedgerCommandExecutor(
        FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
    ).execute(_proposal_command(**overrides), IDENTITY)


def test_repair_proposal_never_touches_the_active_plan():
    """The whole point: a proposal is not an activation."""
    transaction = _proposal_transaction()
    _execute_proposal(transaction)

    tables = [item["table"] for item in transaction.inserts]
    # No PlanRevisions row, no Orders row, no Vehicles update: the active
    # plan is untouched and rev07 stays authoritative.
    assert "PlanRevisions" not in tables
    assert "Orders" not in tables
    assert transaction.updates == []
    assert set(tables) == {"PlanConstraints", "InboundEvents", "Receipts"}


def test_repair_proposal_is_written_against_the_revision_it_repairs():
    transaction = _proposal_transaction()
    _execute_proposal(transaction)
    constraint = next(i for i in transaction.inserts if i["table"] == "PlanConstraints")
    row = constraint["values"][0]
    assert row[2] == "rev07"           # written on the SOURCE revision
    assert row[3] == "REPAIR_PROPOSAL"
    detail = json.loads(row[5])
    assert detail["authority"] == "AGENT_PROPOSAL"
    assert detail["activation_supported"] is False
    assert detail["proposed_revision"] == "rev08"


def test_repair_proposal_binds_the_exact_diff_the_approval_will_sign():
    """Proposal and approval must hash the same diff, or approval fails."""
    from full_shelf_domain.kms import compute_plan_diff_hash
    from full_shelf_domain.models import PlanDiff

    transaction = _proposal_transaction()
    _execute_proposal(transaction)
    detail = json.loads(
        next(i for i in transaction.inserts if i["table"] == "PlanConstraints")["values"][0][5]
    )
    expected = compute_plan_diff_hash(PlanDiff(
        source_revision="rev07", proposed_revision="rev08",
        reroute_order_id="O202", reroute_cases=22,
        reroute_target_vehicle="TRUCK-02",
        pickup_order_id="O203", pickup_cases=20,
        plan_diff_hash="",
    ))
    assert detail["plan_diff_hash"] == expected
    assert detail["plan_diff"]["reroute_cases"] == 22
    assert detail["plan_diff"]["pickup_cases"] == 20


def test_repair_proposal_records_projected_capacity_arithmetic():
    """36 committed + 22 rerouted = 58, within Truck 2's 60."""
    transaction = _proposal_transaction()
    _execute_proposal(transaction)
    detail = json.loads(
        next(i for i in transaction.inserts if i["table"] == "PlanConstraints")["values"][0][5]
    )
    assert detail["absorbing_vehicle_committed_cases"] == 36
    assert detail["absorbing_vehicle_projected_cases"] == 58
    assert detail["absorbing_vehicle_capacity_cases"] == 60


def test_infeasible_repair_proposal_fails_closed():
    """A reroute that overruns the absorbing vehicle is not a proposal."""
    transaction = _proposal_transaction()
    with pytest.raises(ValueError, match="PROPOSED_REROUTE_EXCEEDS_ABSORBING_CAPACITY"):
        _execute_proposal(transaction, absorbing_vehicle_committed_cases=50)
    assert transaction.inserts == []
    assert transaction.upserts == []
    assert transaction.updates == []


def test_proposal_cannot_reroute_onto_the_failed_vehicle():
    transaction = _proposal_transaction()
    with pytest.raises(ValueError, match="CANNOT_REROUTE_ONTO_THE_FAILED_VEHICLE"):
        _execute_proposal(transaction, plan_diff={"reroute_target_vehicle": "TRUCK-01"})
    assert transaction.inserts == []


def test_proposal_whose_target_revision_already_exists_fails_closed():
    """An 'already activated' proposal is an activation attempt."""
    transaction = _proposal_transaction(
        statuses={"rev07": "ACTIVE", "rev08": "ACTIVE"})
    with pytest.raises(ValueError, match="PROPOSED_REVISION_ALREADY_EXISTS"):
        _execute_proposal(transaction)
    assert transaction.inserts == []


def test_proposal_against_a_superseded_revision_fails_closed():
    """A proposal for rev07 cannot land once rev08 is active.

    The generic stale-revision guard catches this before the proposal's own
    check, which is the stronger outcome: it writes a DENIED receipt and no
    constraint, so a replayed proposal cannot reappear against a plan that
    already moved on.
    """
    transaction = _proposal_transaction(active="rev08",
                                        statuses={"rev08": "ACTIVE"})
    result = _execute_proposal(transaction)
    assert result.receipt["status"] == "DENIED"
    assert result.additional_mutations == 0
    assert [i["table"] for i in transaction.inserts] == ["Receipts"]
    assert transaction.upserts == []
    assert transaction.updates == []


def test_duplicate_fleet_event_is_idempotent():
    """A redelivered fault applies no further mutations."""
    command = _proposal_command()
    timestamp = datetime(2026, 8, 14, 8, 21, tzinfo=timezone.utc)
    existing = (
        "RCT-PROP-STABLE", command.command_id, "rev07",
        "PERSIST_REPAIR_PROPOSAL", "SUCCESS", 2,
        "PERSIST_REPAIR_PROPOSAL committed", "0123456789abcdef0123456789abcdef",
        timestamp, IDENTITY.subject, IDENTITY.email,
        "FULFILLMENT_RECOVERY_PLANNER", command.request_fingerprint(),
    )

    class ReplayTransaction(type(_proposal_transaction())):
        def execute_sql(self, sql, params, param_types):
            if "idempotency_key" in sql:
                return [existing]
            return super().execute_sql(sql, params, param_types)

    transaction = ReplayTransaction()
    result = SpannerLedgerCommandExecutor(
        FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
    ).execute(command, IDENTITY)

    assert result.idempotent_replay is True
    assert result.additional_mutations == 0
    assert transaction.inserts == []
    assert transaction.upserts == []


def test_only_the_recovery_planner_may_propose_a_repair():
    transaction = _proposal_transaction()
    result = SpannerLedgerCommandExecutor(
        FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}
    ).execute(
        coordinator_command(
            command_id="CMD-PROPOSAL-WRONG-ROLE",
            idempotency_key="audit:PLAN-ALT:rev07:repair-proposal",
            agent_role="PARTNER_OPERATIONS_AGENT",
            command_type=LedgerCommandType.PERSIST_REPAIR_PROPOSAL,
            expected_plan_revision="rev07",
            payload=_proposal_payload(),
        ),
        IDENTITY,
    )
    assert result.receipt["status"] == "DENIED"
    assert result.additional_mutations == 0
    assert [i["table"] for i in transaction.inserts] == ["Receipts"]
