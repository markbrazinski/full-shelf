from typing import Tuple
from .models import PlanStatus, IncidentStatus


class PlanRevisionStateMachine:
    VALID_TRANSITIONS = {
        ("rev07", PlanStatus.ACTIVE): [("rev08", PlanStatus.ACTIVE)],  # Truck breakdown recovery: rev07 -> rev08
        ("rev08", PlanStatus.ACTIVE): [("rev09", PlanStatus.INVALIDATED_RECALL)],  # Lettuce recall invalidation: rev08 -> rev09
    }

    @classmethod
    def can_transition(cls, current_rev: str, current_status: PlanStatus, next_rev: str, next_status: PlanStatus) -> bool:
        allowed = cls.VALID_TRANSITIONS.get((current_rev, current_status), [])
        return (next_rev, next_status) in allowed


class IncidentStateMachine:
    VALID_TRANSITIONS = {
        ("TRUCK_BREAKDOWN", IncidentStatus.ACTIVE): [IncidentStatus.RESOLVED],
        ("FOOD_SAFETY_RECALL", IncidentStatus.DETECTED): [IncidentStatus.SCOPING],
        ("FOOD_SAFETY_RECALL", IncidentStatus.SCOPING): [IncidentStatus.CONTAINMENT_IN_PROGRESS],
        ("FOOD_SAFETY_RECALL", IncidentStatus.CONTAINMENT_IN_PROGRESS): [IncidentStatus.PARTIALLY_CONTAINED],
        ("FOOD_SAFETY_RECALL", IncidentStatus.PARTIALLY_CONTAINED): [IncidentStatus.CONTAINED],
        ("FOOD_SAFETY_RECALL", IncidentStatus.CONTAINED): [IncidentStatus.CLOSED],
    }

    @classmethod
    def can_transition(cls, incident_type: str, current_status: IncidentStatus, next_status: IncidentStatus) -> bool:
        allowed = cls.VALID_TRANSITIONS.get((incident_type, current_status), [])
        return next_status in allowed
