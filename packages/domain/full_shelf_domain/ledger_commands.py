"""Typed deterministic command contracts for the plan-ledger boundary."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Dict, Literal, Type

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LedgerCommandType(str, Enum):
    SAVE_PLAN_REVISION = "SAVE_PLAN_REVISION"
    PERSIST_REPAIR_APPROVAL = "PERSIST_REPAIR_APPROVAL"
    ACTIVATE_APPROVED_REPAIR_PLAN = "ACTIVATE_APPROVED_REPAIR_PLAN"
    INVALIDATE_PLAN = "INVALIDATE_PLAN"
    ALLOCATE_SAFE_STOCK = "ALLOCATE_SAFE_STOCK"
    PERSIST_COORDINATOR = "PERSIST_COORDINATOR"
    OPEN_RECALL_INCIDENT = "OPEN_RECALL_INCIDENT"
    RECORD_ACKNOWLEDGMENT_HOLD = "RECORD_ACKNOWLEDGMENT_HOLD"
    SET_INCIDENT_STATUS = "SET_INCIDENT_STATUS"
    ACTIVATE_MOVEMENT_BARRIER = "ACTIVATE_MOVEMENT_BARRIER"
    RECORD_REFUSAL = "RECORD_REFUSAL"
    CREATE_NEXT_DAY_DRAFT = "CREATE_NEXT_DAY_DRAFT"
    PERSIST_REPAIR_PROPOSAL = "PERSIST_REPAIR_PROPOSAL"


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanOrderPayload(StrictPayload):
    order_id: str = Field(min_length=1, max_length=64)
    destination_agency_id: str = Field(min_length=1, max_length=64)
    destination_agency_name: str = Field(min_length=1, max_length=128)
    cases: int = Field(gt=0)
    lot_id: str = Field(min_length=1, max_length=64)
    assigned_vehicle_id: str | None = Field(default=None, max_length=64)
    status: str = Field(min_length=1, max_length=32)


class OperatingLotPayload(StrictPayload):
    lot_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=64)
    produce_type: str = Field(min_length=1, max_length=128)
    hazard_status: str = Field(min_length=1, max_length=32)
    total_cases: int = Field(ge=0)


class OperatingVehiclePayload(StrictPayload):
    vehicle_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    max_capacity_cases: int = Field(gt=0)
    current_load_cases: int = Field(ge=0)
    is_operational: bool


class OperatingCustodyNodePayload(StrictPayload):
    node_id: str = Field(min_length=1, max_length=64)
    node_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    on_hand_cases: int = Field(ge=0)
    acknowledgment_status: Literal["CONFIRMED", "UNCONFIRMED", "TOPOLOGY_ONLY"]


class OperatingCustodyEdgePayload(StrictPayload):
    edge_id: str = Field(min_length=1, max_length=64)
    source_node_id: str = Field(min_length=1, max_length=64)
    target_node_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    case_count: int = Field(ge=0)
    is_sub_distribution: bool = False


class OperatingPlanDefinition(StrictPayload):
    tenant_name: str = Field(min_length=1, max_length=256)
    plan_id: str = Field(min_length=1, max_length=64)
    revision: Literal["rev07"]
    status: Literal["ACTIVE"]
    orders: list[PlanOrderPayload] = Field(min_length=1)
    lots: list[OperatingLotPayload] = Field(min_length=1)
    vehicles: list[OperatingVehiclePayload] = Field(min_length=1)
    custody_nodes: list[OperatingCustodyNodePayload] = Field(min_length=1)
    custody_edges: list[OperatingCustodyEdgePayload] = Field(min_length=1)


class OperatingDayRequest(StrictPayload):
    event_type: Literal["PLAN_DAY_REQUESTED"]
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,54}$")
    operating_day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    operating_plan: OperatingPlanDefinition


class RecurringDailyRequest(StrictPayload):
    """Date-free Scheduler input; managed delivery time supplies the day."""

    event_type: Literal["PLAN_DAY_REQUESTED"]
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,54}$")
    operating_plan: OperatingPlanDefinition


class NextDayRequest(StrictPayload):
    """Date-free next-day Scheduler input; managed delivery time supplies the day."""

    event_type: Literal["PLAN_NEXT_DAY_REQUESTED"]
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")


class SavePlanRevisionPayload(OperatingPlanDefinition):
    logical_tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,54}$")
    operating_day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    request_type: Literal["PLAN_DAY_REQUESTED"]
    authority_scope: str = Field(min_length=3, max_length=128)


class SignedRepairDiffPayload(StrictPayload):
    reroute_order_id: str = Field(min_length=1, max_length=64)
    reroute_cases: int = Field(gt=0)
    reroute_target_vehicle: str = Field(min_length=1, max_length=64)
    pickup_order_id: str = Field(min_length=1, max_length=64)
    pickup_cases: int = Field(gt=0)


class PersistRepairProposalPayload(StrictPayload):
    """A non-authoritative repair proposal awaiting human approval.

    Deliberately carries NO approver, NO KMS signature and NO activation
    intent: it is what the agents propose, not what anyone authorized. The
    executor writes it as a constraint on the SOURCE revision, so the active
    plan is untouched and rev07 stays authoritative until approval.

    plan_diff is the same shape the approval later signs, so the proposal an
    operator sees and the diff KMS binds cannot diverge.
    """

    proposal_id: str = Field(min_length=1, max_length=64)
    source_event_id: str = Field(min_length=1, max_length=256)
    plan_id: str = Field(min_length=1, max_length=64)
    source_revision: str = Field(min_length=1, max_length=32)
    proposed_revision: str = Field(min_length=1, max_length=32)
    vehicle_id: str = Field(min_length=1, max_length=64)
    absorbing_vehicle_capacity_cases: int = Field(gt=0)
    absorbing_vehicle_committed_cases: int = Field(ge=0)
    plan_diff: SignedRepairDiffPayload

    @model_validator(mode="after")
    def _proposal_is_feasible_and_not_an_activation(self):
        if self.source_revision == self.proposed_revision:
            raise ValueError("PROPOSAL_MUST_ADVANCE_A_REVISION")
        # The absorbing vehicle must actually fit the rerouted cases. A
        # proposal that cannot be executed is not a proposal.
        after = self.absorbing_vehicle_committed_cases + self.plan_diff.reroute_cases
        if after > self.absorbing_vehicle_capacity_cases:
            raise ValueError("PROPOSED_REROUTE_EXCEEDS_ABSORBING_CAPACITY")
        if self.plan_diff.reroute_order_id == self.plan_diff.pickup_order_id:
            raise ValueError("REROUTE_AND_PICKUP_MUST_BE_DISTINCT_ORDERS")
        if self.plan_diff.reroute_target_vehicle == self.vehicle_id:
            raise ValueError("CANNOT_REROUTE_ONTO_THE_FAILED_VEHICLE")
        return self


class PersistRepairApprovalPayload(StrictPayload):
    operating_day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    authority_scope: str = Field(min_length=3, max_length=128)
    plan_id: str = Field(min_length=1, max_length=64)
    source_revision: str = Field(min_length=1, max_length=32)
    proposed_revision: str = Field(min_length=1, max_length=32)
    approval_id: str = Field(min_length=1, max_length=64)
    approver_subject: str = Field(min_length=1, max_length=128)
    approver_email: str = Field(min_length=1, max_length=320)
    oauth_audience: str = Field(min_length=1, max_length=256)
    plan_diff_hash: str = Field(min_length=64, max_length=64)
    kms_key_version: str = Field(min_length=1, max_length=512)
    kms_signature: str = Field(min_length=1)
    expires_at: str = Field(min_length=1, max_length=64)
    plan_diff: SignedRepairDiffPayload


class ActivateApprovedRepairPlanPayload(StrictPayload):
    approval_id: str = Field(min_length=1, max_length=64)
    operating_day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    authority_scope: str = Field(min_length=3, max_length=128)
    plan_id: str = Field(min_length=1, max_length=64)
    source_revision: str = Field(min_length=1, max_length=32)
    proposed_revision: str = Field(min_length=1, max_length=32)


class InvalidatePlanPayload(StrictPayload):
    plan_id: str = Field(min_length=1, max_length=64)
    revision: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1)


class RecoveryAllocationPayload(StrictPayload):
    allocation_id: str = Field(min_length=1, max_length=64)
    agency_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    cases: int = Field(gt=0)


class RecoveryShortfallPayload(StrictPayload):
    shortfall_id: str = Field(min_length=1, max_length=64)
    agency_id: str = Field(min_length=1, max_length=64)
    cases: int = Field(gt=0)


class AllocateSafeStockPayload(StrictPayload):
    incident_id: str = Field(min_length=1, max_length=64)
    allocations: list[RecoveryAllocationPayload] = Field(min_length=1)
    shortfalls: list[RecoveryShortfallPayload] = Field(min_length=1)


class PersistCoordinatorPayload(StrictPayload):
    coordinator_id: str = Field(min_length=1, max_length=64)
    state: str = Field(min_length=1, max_length=64)
    checkpoint: str = Field(min_length=1, max_length=64)
    active_plan_revision: str = Field(min_length=1, max_length=32)
    child_incident_ids: list[str] = Field(default_factory=list)


class OpenRecallIncidentPayload(StrictPayload):
    incident_id: str = Field(min_length=1, max_length=64)
    coordinator_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    source_event_id: str = Field(min_length=1, max_length=256)
    source_publish_time: str = Field(min_length=1, max_length=64)
    model_armor_correlation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    details: Dict[str, Any]


class RecordAcknowledgmentHoldPayload(StrictPayload):
    incident_id: str = Field(min_length=1, max_length=64)
    hold_incident_id: str = Field(min_length=1, max_length=64)
    coordinator_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    site_id: str = Field(min_length=1, max_length=64)
    unconfirmed_cases: int = Field(gt=0)
    task_name: str = Field(min_length=1)
    delivery_subject: str = Field(min_length=1, max_length=128)
    delivery_email: str = Field(min_length=1, max_length=320)
    delivery_audience: str = Field(min_length=1, max_length=512)


class NextDayBarrierPayload(StrictPayload):
    barrier_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)


class NextDayShortfallPayload(StrictPayload):
    shortfall_id: str = Field(min_length=1, max_length=64)
    agency_id: str = Field(min_length=1, max_length=64)
    cases: int = Field(gt=0)


class NextDayAcknowledgmentHoldPayload(StrictPayload):
    hold_incident_id: str = Field(min_length=1, max_length=64)
    site_id: str = Field(min_length=1, max_length=64)
    unconfirmed_cases: int = Field(gt=0)


class NextDayCandidateStopPayload(StrictPayload):
    """One deterministic candidate stop, persisted as a child Order row.

    A candidate is subordinate to the DRAFT_WITH_CONSTRAINTS revision and is
    never an active commitment. Its status is fixed so no caller can smuggle
    an activatable state through this path.
    """

    order_id: str = Field(min_length=1, max_length=64)
    agency_id: str = Field(min_length=1, max_length=64)
    agency_name: str = Field(min_length=1, max_length=128)
    cases: int = Field(gt=0)
    lot_id: str = Field(min_length=1, max_length=64)
    vehicle_id: str = Field(min_length=1, max_length=64)
    sequence: int = Field(ge=1)
    shortfall_id: str = Field(min_length=1, max_length=64)
    status: Literal["CANDIDATE"]


class NextDayCandidateVehiclePayload(StrictPayload):
    vehicle_id: str = Field(min_length=1, max_length=64)
    capacity_cases: int = Field(gt=0)
    committed_load_cases: int = Field(ge=0)
    candidate_load_cases: int = Field(ge=0)
    stops: list[NextDayCandidateStopPayload] = Field(min_length=1)


class NextDayUnassignedDemandPayload(StrictPayload):
    """Demand the draft could not meet from confirmed-safe supply."""

    shortfall_id: str = Field(min_length=1, max_length=64)
    agency_id: str = Field(min_length=1, max_length=64)
    cases: int = Field(gt=0)
    reason: Literal[
        "NO_CONFIRMED_SAFE_LOT_WITH_SUFFICIENT_CASES",
        "NO_REMAINING_TRANSPORT_CAPACITY",
    ]


class CreateNextDayDraftPayload(StrictPayload):
    source_event_id: str = Field(min_length=1, max_length=256)
    source_operating_day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    event_type: Literal["PLAN_NEXT_DAY_REQUESTED"]
    operating_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    plan_id: str = Field(min_length=1, max_length=64)
    revision: Literal["rev01"]
    status: Literal["DRAFT_WITH_CONSTRAINTS"]
    coordinator_id: str = Field(min_length=1, max_length=64)
    barriers: list[NextDayBarrierPayload] = Field(min_length=1)
    shortfalls: list[NextDayShortfallPayload] = Field(min_length=1)
    acknowledgment_holds: list[NextDayAcknowledgmentHoldPayload] = Field(min_length=1)
    human_approval_required: Literal[True]
    # Deterministic candidate schedule. Optional so an existing caller that
    # commits constraints alone stays valid; the executor persists these as
    # child Orders of the draft revision and re-derives nothing.
    candidate_vehicles: list[NextDayCandidateVehiclePayload] = Field(
        default_factory=list
    )
    unassigned_demand: list[NextDayUnassignedDemandPayload] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _candidate_arithmetic_holds(self):
        """Fail closed on any payload whose own arithmetic does not hold.

        Capacity and load are checked here so a tampered payload is rejected
        before the executor opens a transaction. The executor re-checks against
        authoritative rows; this is the cheap first gate, not the only one.
        """
        seen_orders: set[str] = set()
        seen_shortfalls: set[str] = set()
        for vehicle in self.candidate_vehicles:
            declared = sum(stop.cases for stop in vehicle.stops)
            if declared != vehicle.candidate_load_cases:
                raise ValueError("CANDIDATE_LOAD_DOES_NOT_MATCH_STOPS")
            if (vehicle.committed_load_cases + vehicle.candidate_load_cases
                    > vehicle.capacity_cases):
                raise ValueError("CANDIDATE_LOAD_EXCEEDS_VEHICLE_CAPACITY")
            expected = list(range(1, len(vehicle.stops) + 1))
            if [stop.sequence for stop in vehicle.stops] != expected:
                raise ValueError("CANDIDATE_STOP_SEQUENCE_NOT_CONTIGUOUS")
            for stop in vehicle.stops:
                if stop.vehicle_id != vehicle.vehicle_id:
                    raise ValueError("CANDIDATE_STOP_VEHICLE_MISMATCH")
                if stop.order_id in seen_orders:
                    raise ValueError("CANDIDATE_ORDER_ID_NOT_UNIQUE")
                seen_orders.add(stop.order_id)
                seen_shortfalls.add(stop.shortfall_id)
        # One shortfall is either scheduled or unassigned, never both.
        for demand in self.unassigned_demand:
            if demand.shortfall_id in seen_shortfalls:
                raise ValueError("SHORTFALL_BOTH_SCHEDULED_AND_UNASSIGNED")
        return self


class SetIncidentStatusPayload(StrictPayload):
    incident_id: str = Field(min_length=1, max_length=64)
    expected_status: str = Field(min_length=1, max_length=64)
    new_status: str = Field(min_length=1, max_length=64)
    terminal_state: str = Field(min_length=1, max_length=64)
    unconfirmed_cases: int | None = Field(default=None, ge=0)


class ActivateMovementBarrierPayload(StrictPayload):
    barrier_id: str = Field(min_length=1, max_length=64)
    incident_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1)
    work_item_id: str = Field(min_length=1, max_length=64)


class RecordRefusalPayload(StrictPayload):
    incident_id: str = Field(min_length=1, max_length=64)
    subject_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=128)
    affected_cases: int = Field(ge=0)


PAYLOAD_MODELS: Dict[LedgerCommandType, Type[StrictPayload]] = {
    LedgerCommandType.SAVE_PLAN_REVISION: SavePlanRevisionPayload,
    LedgerCommandType.PERSIST_REPAIR_APPROVAL: PersistRepairApprovalPayload,
    LedgerCommandType.ACTIVATE_APPROVED_REPAIR_PLAN: ActivateApprovedRepairPlanPayload,
    LedgerCommandType.INVALIDATE_PLAN: InvalidatePlanPayload,
    LedgerCommandType.ALLOCATE_SAFE_STOCK: AllocateSafeStockPayload,
    LedgerCommandType.PERSIST_COORDINATOR: PersistCoordinatorPayload,
    LedgerCommandType.OPEN_RECALL_INCIDENT: OpenRecallIncidentPayload,
    LedgerCommandType.RECORD_ACKNOWLEDGMENT_HOLD: RecordAcknowledgmentHoldPayload,
    LedgerCommandType.SET_INCIDENT_STATUS: SetIncidentStatusPayload,
    LedgerCommandType.ACTIVATE_MOVEMENT_BARRIER: ActivateMovementBarrierPayload,
    LedgerCommandType.RECORD_REFUSAL: RecordRefusalPayload,
    LedgerCommandType.CREATE_NEXT_DAY_DRAFT: CreateNextDayDraftPayload,
    LedgerCommandType.PERSIST_REPAIR_PROPOSAL: PersistRepairProposalPayload,
}


class LedgerCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=64)
    incident_id: str = Field(min_length=1, max_length=64)
    agent_role: str = Field(min_length=1, max_length=64)
    command_type: LedgerCommandType
    expected_plan_revision: str | None = Field(default=None, max_length=32)
    trace_id: str = Field(min_length=16, max_length=128)
    payload: Dict[str, Any]

    def validated_payload(self) -> StrictPayload:
        return PAYLOAD_MODELS[self.command_type].model_validate(self.payload)

    def stable_receipt_id(self) -> str:
        material = f"{self.tenant_id}\x00{self.idempotency_key}".encode("utf-8")
        digest = hashlib.sha256(material).hexdigest()[:24].upper()
        return f"RCT-{digest}"

    def request_fingerprint(self) -> str:
        """Hash mutation semantics while excluding delivery trace/command IDs."""
        material = {
            "tenant_id": self.tenant_id,
            "incident_id": self.incident_id,
            "agent_role": self.agent_role,
            "command_type": self.command_type.value,
            "expected_plan_revision": self.expected_plan_revision,
            "payload": self.validated_payload().model_dump(mode="json"),
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
