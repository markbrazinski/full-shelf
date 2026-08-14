"""Spanner-backed deterministic execution for authenticated ledger commands."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from google.cloud import spanner

from .identity import VerifiedGoogleIdentity
from .ledger_commands import (
    AllocateSafeStockPayload,
    ApplyRepairPlanPayload,
    ActivateApprovedRepairPlanPayload,
    ActivateMovementBarrierPayload,
    CreateNextDayDraftPayload,
    InvalidatePlanPayload,
    LedgerCommand,
    LedgerCommandType,
    OpenRecallIncidentPayload,
    PersistCoordinatorPayload,
    PersistRepairApprovalPayload,
    RecordRefusalPayload,
    RecordAcknowledgmentHoldPayload,
    SavePlanRevisionPayload,
    SetIncidentStatusPayload,
)
from .kms import compute_plan_diff_hash
from .models import PlanDiff
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
        LedgerCommandType.PERSIST_REPAIR_APPROVAL: {"FULFILLMENT_RECOVERY_PLANNER"},
        LedgerCommandType.ACTIVATE_APPROVED_REPAIR_PLAN: {"FULFILLMENT_RECOVERY_PLANNER"},
        LedgerCommandType.INVALIDATE_PLAN: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.ALLOCATE_SAFE_STOCK: {"FULFILLMENT_RECOVERY_PLANNER"},
        LedgerCommandType.PERSIST_COORDINATOR: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.OPEN_RECALL_INCIDENT: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.RECORD_ACKNOWLEDGMENT_HOLD: {"PARTNER_OPERATIONS_AGENT"},
        LedgerCommandType.SET_INCIDENT_STATUS: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.ACTIVATE_MOVEMENT_BARRIER: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.RECORD_REFUSAL: {"INCIDENT_COORDINATOR"},
        LedgerCommandType.CREATE_NEXT_DAY_DRAFT: {"FULFILLMENT_RECOVERY_PLANNER"},
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
            expected_revision_matches = active_revision == command.expected_plan_revision
            if (
                command.command_type is LedgerCommandType.CREATE_NEXT_DAY_DRAFT
                and command.expected_plan_revision is not None
            ):
                expected_revision_matches = self._revision_status(
                    transaction, command.tenant_id, command.expected_plan_revision
                ) == "INVALIDATED_RECALL"
            if (
                command.expected_plan_revision is not None
                and not expected_revision_matches
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
            "WHERE tenant_id = @tenant_id AND status = 'ACTIVE' "
            "ORDER BY created_at DESC LIMIT 1",
            params={"tenant_id": tenant_id},
            param_types={"tenant_id": spanner.param_types.STRING},
        )
        return next((row[0] for row in rows), None)

    @staticmethod
    def _revision_status(
        transaction: Any, tenant_id: str, revision: str
    ) -> str | None:
        rows = transaction.execute_sql(
            "SELECT status FROM PlanRevisions WHERE tenant_id = @tenant_id "
            "AND revision = @revision ORDER BY created_at DESC LIMIT 1",
            params={"tenant_id": tenant_id, "revision": revision},
            param_types={
                "tenant_id": spanner.param_types.STRING,
                "revision": spanner.param_types.STRING,
            },
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
            lot_ids = [lot.lot_id for lot in payload.lots]
            vehicle_ids = [vehicle.vehicle_id for vehicle in payload.vehicles]
            order_ids = [order.order_id for order in payload.orders]
            node_ids = [node.node_id for node in payload.custody_nodes]
            edge_ids = [edge.edge_id for edge in payload.custody_edges]
            for values, error in (
                (lot_ids, "DUPLICATE_LOT_ID"),
                (vehicle_ids, "DUPLICATE_VEHICLE_ID"),
                (order_ids, "DUPLICATE_ORDER_ID"),
                (node_ids, "DUPLICATE_CUSTODY_NODE_ID"),
                (edge_ids, "DUPLICATE_CUSTODY_EDGE_ID"),
            ):
                if len(values) != len(set(values)):
                    raise ValueError(error)
            for vehicle in payload.vehicles:
                if vehicle.current_load_cases > vehicle.max_capacity_cases:
                    raise ValueError("VEHICLE_LOAD_EXCEEDS_CAPACITY")
            for order in payload.orders:
                if order.lot_id not in lot_ids:
                    raise ValueError("ORDER_LOT_NOT_DEFINED")
                if (order.assigned_vehicle_id is not None
                        and order.assigned_vehicle_id not in vehicle_ids):
                    raise ValueError("ORDER_VEHICLE_NOT_DEFINED")
            for edge in payload.custody_edges:
                if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
                    raise ValueError("CUSTODY_EDGE_NODE_NOT_DEFINED")
                if edge.lot_id not in lot_ids:
                    raise ValueError("CUSTODY_EDGE_LOT_NOT_DEFINED")
            tenant_exists = next(iter(transaction.execute_sql(
                "SELECT tenant_id FROM Tenants WHERE tenant_id = @tenant_id",
                params={"tenant_id": command.tenant_id},
                param_types={"tenant_id": spanner.param_types.STRING},
            )), None)
            mutation_count = 0
            if tenant_exists is None:
                transaction.insert(
                    table="Tenants",
                    columns=["tenant_id", "name", "created_at"],
                    values=[[command.tenant_id, payload.tenant_name,
                             spanner.COMMIT_TIMESTAMP]],
                )
                mutation_count += 1
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
            transaction.insert(
                table="Lots",
                columns=["tenant_id", "lot_id", "code", "produce_type",
                         "hazard_status", "total_cases", "created_at"],
                values=[[command.tenant_id, lot.lot_id, lot.code, lot.produce_type,
                         lot.hazard_status, lot.total_cases, spanner.COMMIT_TIMESTAMP]
                        for lot in payload.lots],
            )
            transaction.insert(
                table="Vehicles",
                columns=["tenant_id", "vehicle_id", "name", "max_capacity_cases",
                         "current_load_cases", "is_operational"],
                values=[[command.tenant_id, vehicle.vehicle_id, vehicle.name,
                         vehicle.max_capacity_cases, vehicle.current_load_cases,
                         vehicle.is_operational] for vehicle in payload.vehicles],
            )
            transaction.insert(
                table="Orders",
                columns=["tenant_id", "plan_id", "revision", "order_id",
                         "destination_agency_id", "destination_agency_name", "cases",
                         "lot_id", "assigned_vehicle_id", "status"],
                values=[[command.tenant_id, payload.plan_id, payload.revision,
                         order.order_id, order.destination_agency_id,
                         order.destination_agency_name, order.cases, order.lot_id,
                         order.assigned_vehicle_id, order.status]
                        for order in payload.orders],
            )
            transaction.insert(
                table="CustodyNodes",
                columns=["tenant_id", "node_id", "node_type", "name", "on_hand_cases"],
                values=[[command.tenant_id, node.node_id, node.node_type, node.name,
                         node.on_hand_cases] for node in payload.custody_nodes],
            )
            transaction.insert(
                table="CustodyEdges",
                columns=["tenant_id", "edge_id", "source_node_id", "target_node_id",
                         "lot_id", "case_count", "is_sub_distribution"],
                values=[[command.tenant_id, edge.edge_id, edge.source_node_id,
                         edge.target_node_id, edge.lot_id, edge.case_count,
                         edge.is_sub_distribution] for edge in payload.custody_edges],
            )
            transaction.insert(
                table="InboundEvents",
                columns=["tenant_id", "source_event_id", "event_type", "status",
                         "payload", "occurred_at"],
                values=[[command.tenant_id, payload.source_event_id,
                         "PLAN_DAY_REQUESTED", "ACCEPTED",
                         json.dumps({"source_publish_time": payload.source_publish_time,
                                     "plan_id": payload.plan_id,
                                     "revision": payload.revision}, sort_keys=True),
                         spanner.COMMIT_TIMESTAMP]],
            )
            return mutation_count + 1 + len(payload.lots) + len(payload.vehicles) \
                + len(payload.orders) + len(payload.custody_nodes) \
                + len(payload.custody_edges) + 1

        if command.command_type is LedgerCommandType.APPLY_REPAIR_PLAN:
            raise ValueError("HUMAN_APPROVAL_REQUIRED")

        if command.command_type is LedgerCommandType.PERSIST_REPAIR_APPROVAL:
            assert isinstance(payload, PersistRepairApprovalPayload)
            if command.expected_plan_revision != payload.source_revision:
                raise ValueError("REPAIR_SOURCE_REVISION_MISMATCH")
            if payload.source_revision == payload.proposed_revision:
                raise ValueError("REPAIR_REVISION_MUST_ADVANCE")
            diff = PlanDiff(
                source_revision=payload.source_revision,
                proposed_revision=payload.proposed_revision,
                plan_diff_hash=payload.plan_diff_hash,
                **payload.plan_diff.model_dump(),
            )
            if compute_plan_diff_hash(diff) != payload.plan_diff_hash:
                raise ValueError("SIGNED_PLAN_DIFF_HASH_MISMATCH")
            transaction.insert(
                table="Approvals",
                columns=[
                    "tenant_id", "approval_id", "incident_id", "plan_id",
                    "source_revision", "proposed_revision", "approver_subject",
                    "approver_email", "oauth_audience", "plan_diff_hash",
                    "plan_diff_json", "kms_key_version", "kms_signature", "expires_at",
                    "verified_at", "trace_id",
                ],
                values=[[command.tenant_id, payload.approval_id, command.incident_id,
                    payload.plan_id, payload.source_revision, payload.proposed_revision,
                    payload.approver_subject, payload.approver_email,
                    payload.oauth_audience, payload.plan_diff_hash,
                    json.dumps(payload.plan_diff.model_dump(), sort_keys=True,
                               separators=(",", ":")),
                    payload.kms_key_version, payload.kms_signature,
                    datetime.fromisoformat(payload.expires_at.replace("Z", "+00:00")),
                    spanner.COMMIT_TIMESTAMP, command.trace_id]],
            )
            return 1

        if command.command_type is LedgerCommandType.ACTIVATE_APPROVED_REPAIR_PLAN:
            assert isinstance(payload, ActivateApprovedRepairPlanPayload)
            if command.expected_plan_revision != payload.source_revision:
                raise ValueError("REPAIR_SOURCE_REVISION_MISMATCH")
            approval_rows = list(transaction.execute_sql(
                "SELECT incident_id, plan_id, source_revision, proposed_revision, "
                "plan_diff_hash, plan_diff_json, expires_at FROM Approvals "
                "WHERE tenant_id = @tenant_id AND approval_id = @approval_id",
                params={
                    "tenant_id": command.tenant_id,
                    "approval_id": payload.approval_id,
                },
                param_types={
                    "tenant_id": spanner.param_types.STRING,
                    "approval_id": spanner.param_types.STRING,
                },
            ))
            if len(approval_rows) != 1:
                raise ValueError("PERSISTED_REPAIR_APPROVAL_NOT_FOUND")
            approval = approval_rows[0]
            if tuple(approval[0:4]) != (
                command.incident_id,
                payload.plan_id,
                payload.source_revision,
                payload.proposed_revision,
            ):
                raise ValueError("PERSISTED_APPROVAL_SCOPE_MISMATCH")
            expires_at = approval[6]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                raise ValueError("PERSISTED_APPROVAL_EXPIRED")
            try:
                plan_diff_values = json.loads(approval[5])
                plan_diff = PlanDiff(
                    source_revision=payload.source_revision,
                    proposed_revision=payload.proposed_revision,
                    plan_diff_hash=approval[4],
                    **plan_diff_values,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("PERSISTED_PLAN_DIFF_MALFORMED") from exc
            if compute_plan_diff_hash(plan_diff) != approval[4]:
                raise ValueError("PERSISTED_PLAN_DIFF_HASH_MISMATCH")
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
            if plan_diff.reroute_order_id == plan_diff.pickup_order_id:
                raise ValueError("SIGNED_REPAIR_TARGETS_MUST_BE_DISTINCT")
            if not {plan_diff.reroute_order_id, plan_diff.pickup_order_id}.issubset(
                {row[0] for row in source_orders}
            ):
                raise ValueError("SIGNED_REPAIR_TARGETS_NOT_FOUND")
            repaired_orders = []
            for source in source_orders:
                order = list(source)
                if order[0] == plan_diff.reroute_order_id:
                    if order[3] != plan_diff.reroute_cases:
                        raise ValueError("SIGNED_REROUTE_QUANTITY_MISMATCH")
                    order[5], order[6] = plan_diff.reroute_target_vehicle, "REROUTED"
                elif order[0] == plan_diff.pickup_order_id:
                    if order[3] != plan_diff.pickup_cases:
                        raise ValueError("SIGNED_PICKUP_QUANTITY_MISMATCH")
                    order[5], order[6] = None, "PARTNER_PICKUP_CONVERTED"
                repaired_orders.append(order)
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
            return 2

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
            transaction.insert(
                table="InboundEvents",
                columns=["tenant_id", "source_event_id", "event_type", "status",
                         "payload", "occurred_at"],
                values=[[command.tenant_id, payload.source_event_id,
                         "RECALL_NOTICE_RECEIVED", "ACCEPTED",
                         json.dumps({"source_publish_time": payload.source_publish_time,
                                     "incident_id": payload.incident_id,
                                     "lot_id": payload.lot_id}, sort_keys=True),
                         spanner.COMMIT_TIMESTAMP]],
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
            return 3

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
                            "delivery_subject": payload.delivery_subject,
                            "delivery_email": payload.delivery_email,
                            "delivery_audience": payload.delivery_audience,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "PARTIALLY_CONTAINED",
                ]],
            )
            transaction.insert(
                table="InboundEvents",
                columns=[
                    "tenant_id", "source_event_id", "event_type", "status",
                    "payload", "occurred_at",
                ],
                values=[[
                    command.tenant_id,
                    payload.task_name,
                    "SITE01_ACKNOWLEDGMENT_DEADLINE",
                    "ACCEPTED",
                    json.dumps(
                        {
                            "incident_id": payload.incident_id,
                            "site_id": payload.site_id,
                            "delivery_subject": payload.delivery_subject,
                            "delivery_email": payload.delivery_email,
                            "delivery_audience": payload.delivery_audience,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    spanner.COMMIT_TIMESTAMP,
                ]],
            )
            return 2

        if command.command_type is LedgerCommandType.CREATE_NEXT_DAY_DRAFT:
            assert isinstance(payload, CreateNextDayDraftPayload)
            barrier = next(iter(transaction.execute_sql(
                "SELECT barrier_id FROM MovementBarriers WHERE tenant_id = @tenant_id "
                "AND lot_id = @lot_id AND status = 'ACTIVE' LIMIT 1",
                params={"tenant_id": command.tenant_id, "lot_id": payload.excluded_lot_id},
                param_types={"tenant_id": spanner.param_types.STRING,
                             "lot_id": spanner.param_types.STRING},
            )), None)
            if barrier is None:
                raise ValueError("ACTIVE_MOVEMENT_BARRIER_REQUIRED")
            shortfall = next(iter(transaction.execute_sql(
                "SELECT shortfall_id FROM RecoveryShortfalls WHERE tenant_id = @tenant_id "
                "AND agency_id = @agency_id AND cases = @cases AND status = 'OPEN' LIMIT 1",
                params={"tenant_id": command.tenant_id,
                        "agency_id": payload.shortfall_agency_id,
                        "cases": payload.shortfall_cases},
                param_types={"tenant_id": spanner.param_types.STRING,
                             "agency_id": spanner.param_types.STRING,
                             "cases": spanner.param_types.INT64},
            )), None)
            if shortfall is None:
                raise ValueError("OPEN_RECOVERY_SHORTFALL_REQUIRED")
            hold_rows = transaction.execute_sql(
                "SELECT details FROM Incidents WHERE tenant_id = @tenant_id "
                "AND incident_type = 'DEADLINE_HOLD' "
                "AND status = 'ACKNOWLEDGMENT_HOLD_ACTIVE'",
                params={"tenant_id": command.tenant_id},
                param_types={"tenant_id": spanner.param_types.STRING},
            )
            hold_matches = False
            for row in hold_rows:
                try:
                    details = json.loads(row[0] or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                if (details.get("site_id") == payload.acknowledgment_site_id
                        and details.get("unconfirmed_cases") == payload.unconfirmed_cases):
                    hold_matches = True
                    break
            if not hold_matches:
                raise ValueError("OPEN_ACKNOWLEDGMENT_HOLD_REQUIRED")

            existing_plan = next(iter(transaction.execute_sql(
                "SELECT status FROM PlanRevisions WHERE tenant_id = @tenant_id "
                "AND plan_id = @plan_id AND revision = @revision",
                params={"tenant_id": command.tenant_id, "plan_id": payload.plan_id,
                        "revision": payload.revision},
                param_types={"tenant_id": spanner.param_types.STRING,
                             "plan_id": spanner.param_types.STRING,
                             "revision": spanner.param_types.STRING},
            )), None)
            if existing_plan and existing_plan[0] != payload.status:
                raise ValueError("NEXT_DAY_PLAN_ALREADY_EXISTS_WITH_DIFFERENT_STATUS")

            mutation_count = 0
            if not existing_plan:
                transaction.insert(
                    table="PlanRevisions",
                    columns=["tenant_id", "plan_id", "revision", "status", "created_at"],
                    values=[[command.tenant_id, payload.plan_id, payload.revision,
                             payload.status, spanner.COMMIT_TIMESTAMP]],
                )
                constraints = [
                    [command.tenant_id, payload.plan_id, payload.revision,
                     "LOT_MOVEMENT_BARRIER", payload.excluded_lot_id,
                     json.dumps({"barrier_id": barrier[0], "status": "ACTIVE"}, sort_keys=True),
                     1, spanner.COMMIT_TIMESTAMP],
                    [command.tenant_id, payload.plan_id, payload.revision,
                     "RECOVERY_PRIORITY", payload.shortfall_agency_id,
                     json.dumps({"cases": payload.shortfall_cases, "status": "OPEN"}, sort_keys=True),
                     2, spanner.COMMIT_TIMESTAMP],
                    [command.tenant_id, payload.plan_id, payload.revision,
                     "ACKNOWLEDGMENT_HOLD", payload.acknowledgment_site_id,
                     json.dumps({"unconfirmed_cases": payload.unconfirmed_cases,
                                 "status": "ACKNOWLEDGMENT_HOLD_ACTIVE"}, sort_keys=True),
                     3, spanner.COMMIT_TIMESTAMP],
                ]
                transaction.insert(
                    table="PlanConstraints",
                    columns=["tenant_id", "plan_id", "revision", "constraint_type",
                             "subject_id", "details", "priority", "created_at"],
                    values=constraints,
                )
                transaction.insert(
                    table="InboundEvents",
                    columns=["tenant_id", "source_event_id", "event_type", "status",
                             "payload", "occurred_at"],
                    values=[[command.tenant_id, payload.source_event_id,
                             "PLAN_NEXT_DAY_REQUESTED", "ACCEPTED",
                             json.dumps({"source_publish_time": payload.source_publish_time,
                                         "operating_date": payload.operating_date}, sort_keys=True),
                             spanner.COMMIT_TIMESTAMP]],
                )
                transaction.insert_or_update(
                    table="Coordinators",
                    columns=["tenant_id", "coordinator_id", "state", "checkpoint",
                             "active_plan_revision", "child_incidents", "updated_at"],
                    values=[[command.tenant_id, payload.coordinator_id,
                             "DRAFT_WITH_CONSTRAINTS", "HUMAN_APPROVAL_REQUIRED",
                             payload.revision, "[]", spanner.COMMIT_TIMESTAMP]],
                )
                mutation_count = 6
            return mutation_count

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
