from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class HazardStatus(str, Enum):
    SAFE = "SAFE"
    RECALLED = "RECALLED"
    QUARANTINED = "QUARANTINED"


class OrderStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    REROUTED = "REROUTED"
    CONVERTED_TO_PICKUP = "CONVERTED_TO_PICKUP"
    BLOCKED_RECALL = "BLOCKED_RECALL"
    SHORTFALL = "SHORTFALL"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED_RECALL = "INVALIDATED_RECALL"


class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    SCOPING = "SCOPING"
    CONTAINMENT_IN_PROGRESS = "CONTAINMENT_IN_PROGRESS"
    PARTIALLY_CONTAINED = "PARTIALLY_CONTAINED"
    CONTAINED = "CONTAINED"
    CLOSED = "CLOSED"
    # Truck-disruption lifecycle states are separate from the recall chain.
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class NodeType(str, Enum):
    WAREHOUSE = "WAREHOUSE"
    VEHICLE = "VEHICLE"
    STAGING = "STAGING"
    AGENCY = "AGENCY"
    SUBSITE = "SUBSITE"
    DIRECT_RESCUE = "DIRECT_RESCUE"


class Lot(BaseModel):
    lot_id: str  # "LTC-4471" or "LTC-5090"
    code: str  # "LTC-4471" or "LTC-5090"
    produce_type: str = "Romaine Lettuce"
    hazard_status: HazardStatus = HazardStatus.SAFE
    hazard_details: Optional[str] = None
    total_cases: int


class Vehicle(BaseModel):
    vehicle_id: str
    name: str
    max_capacity_cases: int = 60
    current_load_cases: int = 0
    is_operational: bool = True


class Order(BaseModel):
    order_id: str
    tenant_id: str = "east-bay-food-bank"
    destination_agency_id: str
    destination_agency_name: str
    cases: int
    lot_id: str
    assigned_vehicle_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PLANNED


class PlanRevision(BaseModel):
    plan_id: str
    tenant_id: str = "east-bay-food-bank"
    revision: str  # e.g., "rev07", "rev08"
    status: PlanStatus = PlanStatus.ACTIVE
    orders: List[Order]
    vehicle_assignments: Dict[str, List[str]]  # vehicle_id -> list of order_ids
    created_at: str


class PlanDiff(BaseModel):
    source_revision: str = "rev07"
    proposed_revision: str = "rev08"
    reroute_order_id: str = "O202"
    reroute_cases: int = 22
    reroute_target_vehicle: str = "TRUCK-02"
    pickup_order_id: str = "O203"
    pickup_cases: int = 20
    plan_diff_hash: str


class ApprovalEnvelope(BaseModel):
    approval_id: str
    rev_id: str = "rev08"
    principal_id: str = "operations-director@fullshelf.org"
    incident_id: str = "INC-TRUCK-01"
    plan_id: str = "PLAN-2026-08-07"
    source_revision: str = "rev07"
    proposed_revision: str = "rev08"
    plan_diff: PlanDiff
    kms_key_version: str = "projects/preflight-hackathon/locations/us-central1/keyRings/full-shelf-keyring/cryptoKeys/approval-signer/cryptoKeyVersions/1"
    kms_signature: str
    expires_at: str


class CustodyNode(BaseModel):
    node_id: str
    node_type: NodeType
    name: str
    on_hand_cases: int


class CustodyEdge(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    lot_id: str
    case_count: int
    is_sub_distribution: bool = False  # True when moving cases forwarded from an agency to a subsite


class Incident(BaseModel):
    incident_id: str
    parent_coordinator_id: str = "day-coord-2026-08-07"
    tenant_id: str = "east-bay-food-bank"
    incident_type: str  # "TRUCK_BREAKDOWN" or "FOOD_SAFETY_RECALL"
    status: IncidentStatus = IncidentStatus.ACTIVE
    affected_lot_id: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None


class Receipt(BaseModel):
    receipt_id: str
    action_id: str
    tenant_id: str = "east-bay-food-bank"
    plan_revision_id: str
    action_type: str
    status: str  # "SUCCESS", "DENIED", "REJECTED"
    timestamp: str
    mutations_applied: int = 0
    message: str
    trace_id: str
