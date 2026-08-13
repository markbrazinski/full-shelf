from full_shelf_domain.models import Incident, IncidentStatus
from full_shelf_domain.state_machines import IncidentStateMachine


def test_truthful_unresolved_terminal_state():
    """
    While Site 01's 8 cases remain unacknowledged, incident state evaluates strictly to
    PARTIALLY_CONTAINED and cannot transition directly to CONTAINED or RESOLVED.
    """
    recall_incident = Incident(
        incident_id="INC-RECALL-01",
        parent_coordinator_id="day-coord-2026-08-07",
        tenant_id="east-bay-food-bank",
        incident_type="FOOD_SAFETY_RECALL",
        status=IncidentStatus.DETECTED,
        affected_lot_id="LTC-4471",
        created_at="2026-08-07T09:35:00Z",
    )

    assert recall_incident.status == IncidentStatus.DETECTED

    for next_status in (
        IncidentStatus.SCOPING,
        IncidentStatus.CONTAINMENT_IN_PROGRESS,
        IncidentStatus.PARTIALLY_CONTAINED,
    ):
        assert IncidentStateMachine.can_transition(
            recall_incident.incident_type,
            recall_incident.status,
            next_status,
        )
        recall_incident.status = next_status

    # Attempting premature transition directly to RESOLVED without containment is invalid
    can_resolve = IncidentStateMachine.can_transition(
        recall_incident.incident_type,
        recall_incident.status,
        IncidentStatus.RESOLVED,
    )
    assert can_resolve is False

    assert recall_incident.status == IncidentStatus.PARTIALLY_CONTAINED
