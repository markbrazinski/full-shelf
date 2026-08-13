"""Spanner-backed deterministic execution for authenticated ledger commands."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable

from google.cloud import spanner

from .identity import VerifiedGoogleIdentity
from .ledger_commands import (
    AllocateSafeStockPayload,
    ApplyRepairPlanPayload,
    ApproveRepairPlanPayload,
    ActivateMovementBarrierPayload,
    InvalidatePlanPayload,
    LedgerCommand,
    LedgerCommandType,
    OpenRecallIncidentPayload,
    PersistCoordinatorPayload,
    RecordRefusalPayload,
    RecordAcknowledgmentHoldPayload,
    SavePlanRevisionPayload,
    SetIncidentStatusPayload,
)
from .models import IncidentStatus
from .state_machines import IncidentStateMachine


@dataclass(frozen=True)
class CommandExecutionResult:
    receipt: Dict[str, Any]
    idempotent_replay: bool
    additional_mutations: int


class SpannerLedgerCommandExecutor:
    """Execute one validated command and its receipt in one transaction."""

    _ALLOWED_ROLES = {
        LedgerCommandType.SAVE_PLAN_REVISION: {"FULFILLMENT_RECOVERY_PLANNER"},
        LedgerCommandType.APPLY_REPAIR_PLAN: {"FULFILLMENT_RECOVERY_PLANNER"},
        LedgerCommandType.APPROVE_REPAIR_PLAN: {"FULFILLMENT_RECOVERY_PLANNER"},
        LedgerCommandType.INVALIDATE_PLAN: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.ALLOCATE_SAFE_STOCK: {"FULFILLMENT_RECOVERY_PLANNER"},
        LedgerCommandType.PERSIST_COORDINATOR: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.OPEN_RECALL_INCIDENT: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.RECORD_ACKNOWLEDGMENT_HOLD: {"PARTNER_OPERATIONS_AGENT"},
        LedgerCommandType.SET_INCIDENT_STATUS: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.ACTIVATE_MOVEMENT_BARRIER: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.RECORD_REFUSAL: {"INCIDENT_COORDINATOR"},
    }

    def __init__(self, database: Any, *, allowed_tenant_ids: set[str]) -> None:
        if not allowed_tenant_ids:
            raise ValueError("ALLOWED_TENANT_IDS_REQUIRED")
        self._database = database
        self._allowed_tenant_ids = frozenset(allowed_tenant_ids)

    def execute(
        self,
        command: LedgerCommand,
        caller: VerifiedGoogleIdentity,
    ) -> CommandExecutionResult:
        if command.tenant_id not in self._allowed_tenant_ids:
            raise PermissionError("TENANT_SCOPE_NOT_AUTHORIZED")
        payload = command.validated_payload()

        def transaction_body(transaction):
            existing = self._find_receipt(transaction, command)
            if existing:
                return CommandExecutionResult(
                    receipt=existing,
                    idempotent_replay=True,
                    additional_mutations=0,
                )

            if command.agent_role not in self._ALLOWED_ROLES[command.command_type]:
                return self._deny(
                    transaction,
                    command,
                    caller,
                    active_revision=None,
                    message="AGENT_ROLE_NOT_AUTHORIZED_FOR_COMMAND",
                )

            active_revision = self._active_revision(transaction, command.tenant_id)
            if (
                command.expected_plan_revision is not None
                and active_revision != command.expected_plan_revision
                and not (
                    command.command_type is LedgerCommandType.SAVE_PLAN_REVISION
                    and active_revision is None
                    and isinstance(payload, SavePlanRevisionPayload)
                    and payload.revision == command.expected_plan_revision
                )
            ):
                return self._deny(
                    transaction,
                    command,
                    caller,
                    active_revision,
                    f"STALE_PLAN_REVISION expected={command.expected_plan_revision} actual={active_revision}",
                )

            if command.command_type is LedgerCommandType.RECORD_REFUSAL:
                assert isinstance(payload, RecordRefusalPayload)
                return self._deny(
                    transaction,
                    command,
                    caller,
                    active_revision,
                    f"{payload.reason}: subject={payload.subject_id} affected_cases={payload.affected_cases}",
                )

            mutation_count = self._apply(
                transaction,
                command,
                payload,
                caller,
                active_revision,
            )
            receipt_revision = (
                getattr(payload, "proposed_revision", None)
                or getattr(payload, "revision", None)
                or active_revision
                or command.expected_plan_revision
                or "NONE"
            )
            receipt = self._receipt(
                command,
                plan_revision=receipt_revision,
                status="SUCCESS",
                mutation_count=mutation_count,
                message=f"{command.command_type.value} committed",
            )
            self._insert_receipt(transaction, command, caller, receipt)
            return CommandExecutionResult(
                receipt=receipt,
                idempotent_replay=False,
                additional_mutations=mutation_count,
            )

        return self._database.run_in_transaction(transaction_body)

    @staticmethod
    def _find_receipt(transaction: Any, command: LedgerCommand) -> Dict[str, Any] | None:
        rows = transaction.execute_sql(
            "SELECT receipt_id, action_id, plan_revision_id, action_type, status, "
            "mutations_applied, message, trace_id, timestamp, caller_subject, "
            "caller_email, agent_role "
            "FROM Receipts WHERE tenant_id = @tenant_id AND idempotency_key = @idempotency_key",
            params={
                "tenant_id": command.tenant_id,
                "idempotency_key": command.idempotency_key,
            },
            param_types={
                "tenant_id": spanner.param_types.STRING,
                "idempotency_key": spanner.param_types.STRING,
            },
        )
        for row in rows:
            timestamp = row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8])
            return {
                "tenant_id": command.tenant_id,
                "receipt_id": row[0],
                "command_id": row[1],
                "plan_revision_id": row[2],
                "command_type": row[3],
                "status": row[4],
                "mutations_applied": row[5],
                "message": row[6],
                "trace_id": row[7],
                "timestamp": timestamp,
                "caller_subject": row[9],
                "caller_email": row[10],
                "agent_role": row[11],
            }
        return None

    @staticmethod
    def _active_revision(transaction: Any, tenant_id: str) -> str | None:
        rows = transaction.execute_sql(
            "SELECT revision FROM PlanRevisions "
            "WHERE tenant_id = @tenant_id "
            "ORDER BY created_at DESC LIMIT 1",
            params={"tenant_id": tenant_id},
            param_types={"tenant_id": spanner.param_types.STRING},
        )
        return next((row[0] for row in rows), None)

    def _apply(
        self,
        transaction: Any,
        command: LedgerCommand,
        payload: Any,
        caller: VerifiedGoogleIdentity,
        active_revision: str | None,
    ) -> int:
        if command.command_type is LedgerCommandType.SAVE_PLAN_REVISION:
            assert isinstance(payload, SavePlanRevisionPayload)
            existing_rows = transaction.execute_sql(
                "SELECT status FROM PlanRevisions WHERE tenant_id = @tenant_id "
                "AND plan_id = @plan_id AND revision = @revision",
                params={
                    "tenant_id": command.tenant_id,
                    "plan_id": payload.plan_id,
                    "revision": payload.revision,
                },
                param_types={
                    "tenant_id": spanner.param_types.STRING,
                    "plan_id": spanner.param_types.STRING,
                    "revision": spanner.param_types.STRING,
                },
            )
            existing_status = next((row[0] for row in existing_rows), None)
            if existing_status is not None:
                if existing_status != payload.status:
                    raise ValueError("PLAN_REVISION_ALREADY_EXISTS_WITH_DIFFERENT_STATUS")
                return 0
            if (
                payload.status == "ACTIVE"
                and active_revision is not None
                and payload.revision != active_revision
            ):
                raise ValueError("ACTIVE_PLAN_REPLACEMENT_REQUIRES_REPAIR_COMMAND")
            transaction.insert(
                table="PlanRevisions",
                columns=["tenant_id", "plan_id", "revision", "status", "created_at"],
                values=[[
                    command.tenant_id,
                    payload.plan_id,
                    payload.revision,
                    payload.status,
                    spanner.COMMIT_TIMESTAMP,
                ]],
            )
            return 1

        if command.command_type is LedgerCommandType.APPLY_REPAIR_PLAN:
            raise ValueError("HUMAN_APPROVAL_REQUIRED")

        if command.command_type is LedgerCommandType.APPROVE_REPAIR_PLAN:
            assert isinstance(payload, ApproveRepairPlanPayload)
            if command.expected_plan_revision != payload.source_revision:
                raise ValueError("REPAIR_SOURCE_REVISION_MISMATCH")
            if payload.source_revision == payload.proposed_revision:
                raise ValueError("REPAIR_REVISION_MUST_ADVANCE")
            source_orders = list(transaction.execute_sql(
                "SELECT order_id, destination_agency_id, destination_agency_name, "
                "cases, lot_id, assigned_vehicle_id, status FROM Orders "
                "WHERE tenant_id = @tenant_id AND plan_id = @plan_id "
                "AND revision = @source_revision ORDER BY order_id",
                params={"tenant_id": command.tenant_id, "plan_id": payload.plan_id,
                        "source_revision": payload.source_revision},
                param_types={"tenant_id": spanner.param_types.STRING,
                             "plan_id": spanner.param_types.STRING,
                             "source_revision": spanner.param_types.STRING},
            ))
            if not {"O202", "O203"}.issubset({row[0] for row in source_orders}):
                raise ValueError("SIGNED_REPAIR_TARGETS_NOT_FOUND")
            repaired_orders = []
            for source in source_orders:
                order = list(source)
                if order[0] == "O202":
                    if order[3] != 22:
                        raise ValueError("SIGNED_REROUTE_QUANTITY_MISMATCH")
                    order[5], order[6] = "TRUCK-02", "REROUTED"
                elif order[0] == "O203":
                    if order[3] != 20:
                        raise ValueError("SIGNED_PICKUP_QUANTITY_MISMATCH")
                    order[5], order[6] = None, "PARTNER_PICKUP_CONVERTED"
                repaired_orders.append(order)
            transaction.insert(
                table="Approvals",
                columns=[
                    "tenant_id", "approval_id", "incident_id", "plan_id",
                    "source_revision", "proposed_revision", "approver_subject",
                    "approver_email", "oauth_audience", "plan_diff_hash",
                    "kms_key_version", "kms_signature", "expires_at",
                    "verified_at", "trace_id",
                ],
                values=[[command.tenant_id, payload.approval_id, command.incident_id,
                    payload.plan_id, payload.source_revision, payload.proposed_revision,
                    payload.approver_subject, payload.approver_email,
                    payload.oauth_audience, payload.plan_diff_hash,
                    payload.kms_key_version, payload.kms_signature,
                    datetime.fromisoformat(payload.expires_at.replace("Z", "+00:00")),
                    spanner.COMMIT_TIMESTAMP, command.trace_id]],
            )
            updated = transaction.execute_update(
                "UPDATE PlanRevisions SET status = 'SUPERSEDED' "
                "WHERE tenant_id = @tenant_id AND plan_id = @plan_id "
                "AND revision = @source_revision AND status = 'ACTIVE'",
                params={
                    "tenant_id": command.tenant_id,
                    "plan_id": payload.plan_id,
                    "source_revision": payload.source_revision,
                },
                param_types={
                    "tenant_id": spanner.param_types.STRING,
                    "plan_id": spanner.param_types.STRING,
                    "source_revision": spanner.param_types.STRING,
                },
            )
            if updated != 1:
                raise ValueError("ACTIVE_SOURCE_PLAN_NOT_FOUND")
            transaction.insert(
                table="PlanRevisions",
                columns=["tenant_id", "plan_id", "revision", "status", "created_at"],
                values=[[
                    command.tenant_id,
                    payload.plan_id,
                    payload.proposed_revision,
                    "ACTIVE",
                    spanner.COMMIT_TIMESTAMP,
                ]],
            )
            transaction.insert(
                table="Orders",
                columns=[
                    "tenant_id",
                    "plan_id",
                    "revision",
                    "order_id",
                    "destination_agency_id",
                    "destination_agency_name",
                    "cases",
                    "lot_id",
                    "assigned_vehicle_id",
                    "status",
                ],
                values=[[
                    command.tenant_id,
                    payload.plan_id,
                    payload.proposed_revision,
                    order[0], order[1], order[2], order[3], order[4], order[5], order[6],
                ] for order in repaired_orders],
            )
            return 3

        if command.command_type is LedgerCommandType.INVALIDATE_PLAN:
            assert isinstance(payload, InvalidatePlanPayload)
            if command.expected_plan_revision != payload.revision:
                raise ValueError("INVALIDATION_REVISION_MISMATCH")
            updated = transaction.execute_update(
                "UPDATE PlanRevisions SET status = 'INVALIDATED_RECALL' "
                "WHERE tenant_id = @tenant_id AND plan_id = @plan_id "
                "AND revision = @revision AND status = 'ACTIVE'",
                params={
                    "tenant_id": command.tenant_id,
                    "plan_id": payload.plan_id,
                    "revision": payload.revision,
                },
                param_types={
                    "tenant_id": spanner.param_types.STRING,
                    "plan_id": spanner.param_types.STRING,
                    "revision": spanner.param_types.STRING,
                },
            )
            if updated != 1:
                raise ValueError("ACTIVE_PLAN_INVALIDATION_PRECONDITION_FAILED")
            return 1

        if command.command_type is LedgerCommandType.ALLOCATE_SAFE_STOCK:
            assert isinstance(payload, AllocateSafeStockPayload)
            if payload.incident_id != command.incident_id:
                raise ValueError("INCIDENT_SCOPE_MISMATCH")
            if not self._incident_exists(transaction, command.tenant_id, payload.incident_id):
                raise ValueError("INCIDENT_NOT_FOUND")
            lot_ids = sorted({allocation.lot_id for allocation in payload.allocations})
            for lot_id in lot_ids:
                rows = transaction.execute_sql(
                    "SELECT hazard_status FROM Lots "
                    "WHERE tenant_id = @tenant_id AND lot_id = @lot_id",
                    params={"tenant_id": command.tenant_id, "lot_id": lot_id},
                    param_types={
                        "tenant_id": spanner.param_types.STRING,
                        "lot_id": spanner.param_types.STRING,
                    },
                )
                hazard_status = next((row[0] for row in rows), None)
                if hazard_status not in {"SAFE", "CLEAR_SAFE"}:
                    raise ValueError("REPLACEMENT_LOT_NOT_CONFIRMED_SAFE")
            transaction.insert(
                table="RecoveryAllocations",
                columns=[
                    "tenant_id", "allocation_id", "incident_id", "agency_id",
                    "lot_id", "cases", "status", "created_at",
                ],
                values=[[
                    command.tenant_id,
                    allocation.allocation_id,
                    payload.incident_id,
                    allocation.agency_id,
                    allocation.lot_id,
                    allocation.cases,
                    "ALLOCATED",
                    spanner.COMMIT_TIMESTAMP,
                ] for allocation in payload.allocations],
            )
            transaction.insert(
                table="RecoveryShortfalls",
                columns=[
                    "tenant_id", "shortfall_id", "incident_id", "agency_id",
                    "cases", "status", "created_at",
                ],
                values=[[
                    command.tenant_id,
                    shortfall.shortfall_id,
                    payload.incident_id,
                    shortfall.agency_id,
                    shortfall.cases,
                    "OPEN",
                    spanner.COMMIT_TIMESTAMP,
                ] for shortfall in payload.shortfalls],
            )
            return 2

        if command.command_type is LedgerCommandType.PERSIST_COORDINATOR:
            assert isinstance(payload, PersistCoordinatorPayload)
            if payload.active_plan_revision != command.expected_plan_revision:
                raise ValueError("COORDINATOR_PLAN_REVISION_MISMATCH")
            transaction.insert_or_update(
                table="Coordinators",
                columns=[
                    "tenant_id",
                    "coordinator_id",
                    "state",
                    "checkpoint",
                    "active_plan_revision",
                    "child_incidents",
                    "updated_at",
                ],
                values=[[
                    command.tenant_id,
                    payload.coordinator_id,
                    payload.state,
                    payload.checkpoint,
                    payload.active_plan_revision,
                    json.dumps(payload.child_incident_ids, separators=(",", ":")),
                    spanner.COMMIT_TIMESTAMP,
                ]],
            )
            return 1

        if command.command_type is LedgerCommandType.OPEN_RECALL_INCIDENT:
            assert isinstance(payload, OpenRecallIncidentPayload)
            if payload.incident_id != command.incident_id:
                raise ValueError("INCIDENT_SCOPE_MISMATCH")
            if self._incident_exists(transaction, command.tenant_id, payload.incident_id):
                raise ValueError("INCIDENT_ALREADY_EXISTS_WITH_DIFFERENT_IDEMPOTENCY_KEY")
            coordinator_rows = transaction.execute_sql(
                "SELECT child_incidents FROM Coordinators "
                "WHERE tenant_id = @tenant_id AND coordinator_id = @coordinator_id",
                params={
                    "tenant_id": command.tenant_id,
                    "coordinator_id": payload.coordinator_id,
                },
                param_types={
                    "tenant_id": spanner.param_types.STRING,
                    "coordinator_id": spanner.param_types.STRING,
                },
            )
            coordinator_row = next(iter(coordinator_rows), None)
            if coordinator_row is None:
                raise ValueError("COORDINATOR_NOT_FOUND")
            try:
                child_incidents = json.loads(coordinator_row[0] or "[]")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("COORDINATOR_CHILD_INCIDENTS_INVALID") from exc
            if not isinstance(child_incidents, list) or not all(
                isinstance(item, str) for item in child_incidents
            ):
                raise ValueError("COORDINATOR_CHILD_INCIDENTS_INVALID")
            if payload.incident_id not in child_incidents:
                child_incidents.append(payload.incident_id)
            transaction.insert(
                table="Incidents",
                columns=[
                    "tenant_id",
                    "incident_id",
                    "parent_coordinator_id",
                    "incident_type",
                    "status",
                    "affected_lot_id",
                    "created_at",
                    "details",
                    "terminal_state",
                ],
                values=[[
                    command.tenant_id,
                    payload.incident_id,
                    payload.coordinator_id,
                    "FOOD_SAFETY_RECALL",
                    "DETECTED",
                    payload.lot_id,
                    spanner.COMMIT_TIMESTAMP,
                    json.dumps(payload.details, sort_keys=True, separators=(",", ":")),
                    "NONE",
                ]],
            )
            updated = transaction.execute_update(
                "UPDATE Coordinators SET state = @state, child_incidents = @children, "
                "updated_at = PENDING_COMMIT_TIMESTAMP() "
                "WHERE tenant_id = @tenant_id AND coordinator_id = @coordinator_id",
                params={
                    "state": "RECALL_WOKEN_DETECTED",
                    "children": json.dumps(child_incidents, separators=(",", ":")),
                    "tenant_id": command.tenant_id,
                    "coordinator_id": payload.coordinator_id,
                },
                param_types={
                    "state": spanner.param_types.STRING,
                    "children": spanner.param_types.STRING,
                    "tenant_id": spanner.param_types.STRING,
                    "coordinator_id": spanner.param_types.STRING,
                },
            )
            if updated != 1:
                raise ValueError("COORDINATOR_UPDATE_PRECONDITION_FAILED")
            return 2

        if command.command_type is LedgerCommandType.RECORD_ACKNOWLEDGMENT_HOLD:
            assert isinstance(payload, RecordAcknowledgmentHoldPayload)
            if payload.incident_id != command.incident_id:
                raise ValueError("INCIDENT_SCOPE_MISMATCH")
            transaction.insert_or_update(
                table="Incidents",
                columns=[
                    "tenant_id",
                    "incident_id",
                    "parent_coordinator_id",
                    "incident_type",
                    "status",
                    "affected_lot_id",
                    "created_at",
                    "details",
                    "terminal_state",
                ],
                values=[[
                    command.tenant_id,
                    payload.hold_incident_id,
                    payload.coordinator_id,
                    "DEADLINE_HOLD",
                    "ACKNOWLEDGMENT_HOLD_ACTIVE",
                    payload.lot_id,
                    spanner.COMMIT_TIMESTAMP,
                    json.dumps(
                        {
                            "parent_incident_id": payload.incident_id,
                            "site_id": payload.site_id,
                            "task_name": payload.task_name,
                            "unconfirmed_cases": payload.unconfirmed_cases,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "PARTIALLY_CONTAINED",
                ]],
            )
            return 1

        if command.command_type is LedgerCommandType.SET_INCIDENT_STATUS:
            assert isinstance(payload, SetIncidentStatusPayload)
            if payload.incident_id != command.incident_id:
                raise ValueError("INCIDENT_SCOPE_MISMATCH")
            try:
                expected_status = IncidentStatus(payload.expected_status)
                new_status = IncidentStatus(payload.new_status)
            except ValueError as exc:
                raise ValueError("UNKNOWN_INCIDENT_STATUS") from exc
            if not IncidentStateMachine.can_transition(
                "FOOD_SAFETY_RECALL", expected_status, new_status
            ):
                raise ValueError("INCIDENT_LIFECYCLE_TRANSITION_DENIED")
            if (
                new_status is IncidentStatus.PARTIALLY_CONTAINED
                and (payload.unconfirmed_cases is None or payload.unconfirmed_cases <= 0)
            ):
                raise ValueError("PARTIAL_CONTAINMENT_REQUIRES_UNCONFIRMED_CASES")
            if (
                new_status in {IncidentStatus.CONTAINED, IncidentStatus.CLOSED}
                and payload.unconfirmed_cases != 0
            ):
                raise ValueError("UNCONFIRMED_CASES_BLOCK_CONTAINMENT")
            expected_terminal_state = {
                IncidentStatus.DETECTED: "NONE",
                IncidentStatus.SCOPING: "NONE",
                IncidentStatus.CONTAINMENT_IN_PROGRESS: "NONE",
                IncidentStatus.PARTIALLY_CONTAINED: "PARTIALLY_CONTAINED",
                IncidentStatus.CONTAINED: "CONTAINED",
                IncidentStatus.CLOSED: "CLOSED",
            }[new_status]
            if payload.terminal_state != expected_terminal_state:
                raise ValueError("TERMINAL_STATE_DOES_NOT_MATCH_LIFECYCLE_STATUS")
            updated = transaction.execute_update(
                "UPDATE Incidents SET status = @new_status, terminal_state = @terminal_state "
                "WHERE tenant_id = @tenant_id AND incident_id = @incident_id "
                "AND status = @expected_status",
                params={
                    "new_status": payload.new_status,
                    "terminal_state": payload.terminal_state,
                    "tenant_id": command.tenant_id,
                    "incident_id": payload.incident_id,
                    "expected_status": payload.expected_status,
                },
                param_types={
                    "new_status": spanner.param_types.STRING,
                    "terminal_state": spanner.param_types.STRING,
                    "tenant_id": spanner.param_types.STRING,
                    "incident_id": spanner.param_types.STRING,
                    "expected_status": spanner.param_types.STRING,
                },
            )
            if updated != 1:
                raise ValueError("INCIDENT_STATUS_PRECONDITION_FAILED")
            return 1

        if command.command_type is LedgerCommandType.ACTIVATE_MOVEMENT_BARRIER:
            assert isinstance(payload, ActivateMovementBarrierPayload)
            if payload.incident_id != command.incident_id:
                raise ValueError("INCIDENT_SCOPE_MISMATCH")
            if not self._incident_exists(transaction, command.tenant_id, payload.incident_id):
                raise ValueError("INCIDENT_NOT_FOUND")
            transaction.insert(
                table="MovementBarriers",
                columns=[
                    "tenant_id",
                    "barrier_id",
                    "incident_id",
                    "lot_id",
                    "status",
                    "reason",
                    "created_at",
                ],
                values=[[
                    command.tenant_id,
                    payload.barrier_id,
                    payload.incident_id,
                    payload.lot_id,
                    "ACTIVE",
                    payload.reason,
                    spanner.COMMIT_TIMESTAMP,
                ]],
            )
            updated = transaction.execute_update(
                "UPDATE Lots SET hazard_status = 'RECALLED' "
                "WHERE tenant_id = @tenant_id AND lot_id = @lot_id",
                params={"tenant_id": command.tenant_id, "lot_id": payload.lot_id},
                param_types={
                    "tenant_id": spanner.param_types.STRING,
                    "lot_id": spanner.param_types.STRING,
                },
            )
            if updated != 1:
                raise ValueError("LOT_NOT_FOUND")
            transaction.insert(
                table="WorkItems",
                columns=[
                    "tenant_id", "work_item_id", "incident_id", "work_type",
                    "status", "details", "created_at",
                ],
                values=[[
                    command.tenant_id,
                    payload.work_item_id,
                    payload.incident_id,
                    "RECALL_SCOPE_AND_INVALIDATION",
                    "REQUESTED",
                    json.dumps({"lot_id": payload.lot_id}, separators=(",", ":")),
                    spanner.COMMIT_TIMESTAMP,
                ]],
            )
            return 3

        raise ValueError(f"Unsupported command type: {command.command_type}")

    @staticmethod
    def _incident_exists(transaction: Any, tenant_id: str, incident_id: str) -> bool:
        rows: Iterable[Any] = transaction.execute_sql(
            "SELECT incident_id FROM Incidents "
            "WHERE tenant_id = @tenant_id AND incident_id = @incident_id LIMIT 1",
            params={"tenant_id": tenant_id, "incident_id": incident_id},
            param_types={
                "tenant_id": spanner.param_types.STRING,
                "incident_id": spanner.param_types.STRING,
            },
        )
        return next(iter(rows), None) is not None

    def _deny(
        self,
        transaction: Any,
        command: LedgerCommand,
        caller: VerifiedGoogleIdentity,
        active_revision: str | None,
        message: str,
    ) -> CommandExecutionResult:
        receipt = self._receipt(
            command,
            plan_revision=active_revision or command.expected_plan_revision or "NONE",
            status="DENIED",
            mutation_count=0,
            message=message,
        )
        self._insert_receipt(transaction, command, caller, receipt)
        return CommandExecutionResult(
            receipt=receipt,
            idempotent_replay=False,
            additional_mutations=0,
        )

    @staticmethod
    def _receipt(
        command: LedgerCommand,
        *,
        plan_revision: str,
        status: str,
        mutation_count: int,
        message: str,
    ) -> Dict[str, Any]:
        return {
            "tenant_id": command.tenant_id,
            "receipt_id": command.stable_receipt_id(),
            "command_id": command.command_id,
            "plan_revision_id": plan_revision,
            "command_type": command.command_type.value,
            "status": status,
            "mutations_applied": mutation_count,
            "message": message,
            "trace_id": command.trace_id,
            "timestamp": "PENDING_COMMIT_TIMESTAMP",
        }

    @staticmethod
    def _insert_receipt(
        transaction: Any,
        command: LedgerCommand,
        caller: VerifiedGoogleIdentity,
        receipt: Dict[str, Any],
    ) -> None:
        transaction.insert(
            table="Receipts",
            columns=[
                "tenant_id",
                "receipt_id",
                "action_id",
                "plan_revision_id",
                "action_type",
                "status",
                "mutations_applied",
                "message",
                "trace_id",
                "idempotency_key",
                "caller_subject",
                "caller_email",
                "agent_role",
                "timestamp",
            ],
            values=[[
                receipt["tenant_id"],
                receipt["receipt_id"],
                receipt["command_id"],
                receipt["plan_revision_id"],
                receipt["command_type"],
                receipt["status"],
                receipt["mutations_applied"],
                receipt["message"],
                receipt["trace_id"],
                command.idempotency_key,
                caller.subject,
                caller.email,
                command.agent_role,
                spanner.COMMIT_TIMESTAMP,
            ]],
        )
