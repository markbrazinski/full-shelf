"""Typed deterministic command contracts for the plan-ledger boundary."""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Dict, Literal, Type

from pydantic import BaseModel, ConfigDict, Field


class LedgerCommandType(str, Enum):
    SAVE_PLAN_REVISION = "SAVE_PLAN_REVISION"
    APPLY_REPAIR_PLAN = "APPLY_REPAIR_PLAN"
    INVALIDATE_PLAN = "INVALIDATE_PLAN"
    ALLOCATE_SAFE_STOCK = "ALLOCATE_SAFE_STOCK"
    PERSIST_COORDINATOR = "PERSIST_COORDINATOR"
    OPEN_RECALL_INCIDENT = "OPEN_RECALL_INCIDENT"
    RECORD_ACKNOWLEDGMENT_HOLD = "RECORD_ACKNOWLEDGMENT_HOLD"
    SET_INCIDENT_STATUS = "SET_INCIDENT_STATUS"
    ACTIVATE_MOVEMENT_BARRIER = "ACTIVATE_MOVEMENT_BARRIER"
    RECORD_REFUSAL = "RECORD_REFUSAL"


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


class SavePlanRevisionPayload(StrictPayload):
    plan_id: str = Field(min_length=1, max_length=64)
    revision: str = Field(min_length=1, max_length=32)
    status: Literal["ACTIVE", "DRAFT_WITH_CONSTRAINTS"]


class ApplyRepairPlanPayload(StrictPayload):
    plan_id: str = Field(min_length=1, max_length=64)
    source_revision: str = Field(min_length=1, max_length=32)
    proposed_revision: str = Field(min_length=1, max_length=32)
    orders: list[PlanOrderPayload] = Field(min_length=1)


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
    details: Dict[str, Any]


class RecordAcknowledgmentHoldPayload(StrictPayload):
    incident_id: str = Field(min_length=1, max_length=64)
    hold_incident_id: str = Field(min_length=1, max_length=64)
    coordinator_id: str = Field(min_length=1, max_length=64)
    lot_id: str = Field(min_length=1, max_length=64)
    site_id: str = Field(min_length=1, max_length=64)
    unconfirmed_cases: int = Field(gt=0)
    task_name: str = Field(min_length=1)


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
    LedgerCommandType.APPLY_REPAIR_PLAN: ApplyRepairPlanPayload,
    LedgerCommandType.INVALIDATE_PLAN: InvalidatePlanPayload,
    LedgerCommandType.ALLOCATE_SAFE_STOCK: AllocateSafeStockPayload,
    LedgerCommandType.PERSIST_COORDINATOR: PersistCoordinatorPayload,
    LedgerCommandType.OPEN_RECALL_INCIDENT: OpenRecallIncidentPayload,
    LedgerCommandType.RECORD_ACKNOWLEDGMENT_HOLD: RecordAcknowledgmentHoldPayload,
    LedgerCommandType.SET_INCIDENT_STATUS: SetIncidentStatusPayload,
    LedgerCommandType.ACTIVATE_MOVEMENT_BARRIER: ActivateMovementBarrierPayload,
    LedgerCommandType.RECORD_REFUSAL: RecordRefusalPayload,
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
