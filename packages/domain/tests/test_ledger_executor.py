from datetime import datetime, timezone

from full_shelf_domain.identity import VerifiedGoogleIdentity
from full_shelf_domain.ledger_commands import LedgerCommand, LedgerCommandType
from full_shelf_domain.ledger_executor import SpannerLedgerCommandExecutor


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
    ):
        self.active_revision = active_revision
        self.existing_receipt = existing_receipt
        self.coordinator_children = coordinator_children
        self.source_orders = source_orders or []
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
        if "FROM Coordinators" in sql:
            return [(self.coordinator_children,)]
        if "FROM Orders" in sql:
            return self.source_orders
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
            "details": {"hazard": "ALTERED_TEST_HAZARD"},
        },
    )
    transaction = FakeTransaction()
    result = SpannerLedgerCommandExecutor(
        FakeDatabase(transaction),
        allowed_tenant_ids={"audit-tenant"},
    ).execute(command, IDENTITY)
    assert result.additional_mutations == 2
    assert [item["table"] for item in transaction.inserts] == ["Incidents", "Receipts"]
    assert transaction.updates[0][1]["children"] == (
        '["INC-TRUCK-ALT","INC-RECALL-ALT"]'
    )


def test_unsigned_repair_command_cannot_activate():
    command = coordinator_command(
        command_type=LedgerCommandType.APPLY_REPAIR_PLAN,
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        payload={"plan_id": "PLAN-ALT", "source_revision": "rev42",
                 "proposed_revision": "rev43", "orders": [{
                     "order_id": "ALT", "destination_agency_id": "AG-ALT",
                     "destination_agency_name": "Altered", "cases": 1,
                     "lot_id": "LOT-ALT", "assigned_vehicle_id": None,
                     "status": "PLANNED"}]},
    )
    transaction = FakeTransaction()
    try:
        SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(command, IDENTITY)
    except ValueError as exc:
        assert str(exc) == "HUMAN_APPROVAL_REQUIRED"
    else:
        raise AssertionError("unsigned repair reached activation")
    assert transaction.inserts == []
    assert transaction.updates == []


def test_approved_repair_derives_only_signed_changes_from_source_orders():
    command = coordinator_command(
        command_type=LedgerCommandType.APPROVE_REPAIR_PLAN,
        agent_role="FULFILLMENT_RECOVERY_PLANNER",
        payload={"plan_id": "PLAN-ALT", "source_revision": "rev42",
                 "proposed_revision": "rev43", "approval_id": "APP-ALT",
                 "approver_subject": "operator-sub", "approver_email": "operator@example.com",
                 "oauth_audience": "client.apps.googleusercontent.com",
                 "plan_diff_hash": "a" * 64, "kms_key_version": "projects/p/keys/k/versions/1",
                 "kms_signature": "signature", "expires_at": "2099-01-01T00:00:00Z"},
    )
    source = [
        ("O201", "AG1", "Agency 1", 18, "LOT-X", "TRUCK-01", "PLANNED"),
        ("O202", "AG2", "Agency 2", 22, "LOT-X", "TRUCK-01", "PLANNED"),
        ("O203", "AG3", "Agency 3", 20, "LOT-X", "TRUCK-01", "PLANNED"),
    ]
    transaction = FakeTransaction(source_orders=source)
    result = SpannerLedgerCommandExecutor(FakeDatabase(transaction), allowed_tenant_ids={"audit-tenant"}).execute(command, IDENTITY)
    assert result.additional_mutations == 3
    assert [item["table"] for item in transaction.inserts] == ["Approvals", "PlanRevisions", "Orders", "Receipts"]
    inserted = transaction.inserts[2]["values"]
    assert inserted[0][-2:] == ["TRUCK-01", "PLANNED"]
    assert inserted[1][-2:] == ["TRUCK-02", "REROUTED"]
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
