from typing import Tuple
from .models import PlanStatus, IncidentStatus


class PlanRevisionStateMachine:
    VALID_TRANSITIONS = {
        ("v1", PlanStatus.ACTIVE): [("v2", PlanStatus.ACTIVE)],  # Truck breakdown recovery: v1 -> v2
        ("v2", PlanStatus.ACTIVE): [("v3", PlanStatus.INVALIDATED_RECALL)],  # Lettuce recall invalidation: v2 -> v3
    }

    @classmethod
    def can_transition(cls, current_rev: str, current_status: PlanStatus, next_rev: str, next_status: PlanStatus) -> bool:
        allowed = cls.VALID_TRANSITIONS.get((current_rev, current_status), [])
        return (next_rev, next_status) in allowed


class IncidentStateMachine:
    VALID_TRANSITIONS = {
        ("TRUCK_BREAKDOWN", IncidentStatus.ACTIVE): [IncidentStatus.RESOLVED],
        ("FOOD_SAFETY_RECALL", IncidentStatus.ACTIVE): [
            IncidentStatus.PARTIALLY_CONTAINED_AWAITING_RECOVERY,
            IncidentStatus.CONTAINED,
        ],
        ("FOOD_SAFETY_RECALL", IncidentStatus.PARTIALLY_CONTAINED_AWAITING_RECOVERY): [IncidentStatus.CONTAINED],
    }

    @classmethod
    def can_transition(cls, incident_type: str, current_status: IncidentStatus, next_status: IncidentStatus) -> bool:
        allowed = cls.VALID_TRANSITIONS.get((incident_type, current_status), [])
        return next_status in allowed
