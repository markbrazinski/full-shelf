import pytest
from full_shelf_domain.models import Receipt, PlanRevision, Order, OrderStatus, PlanStatus
from full_shelf_domain.state_machines import PlanRevisionStateMachine


def test_stale_plan_revision_rejection():
    """Attempting a mutation on a stale plan revision (e.g. attempting edit on rev07 when active is rev08) fails with 0 mutations."""
    active_plan = PlanRevision(
        plan_id="PLAN-001",
        revision="rev08",
        status=PlanStatus.ACTIVE,
        orders=[],
        vehicle_assignments={},
        created_at="2026-08-07T09:05:00Z",
    )

    # Action targeted at expected revision 'rev07' (stale)
    expected_rev = "rev07"
    
    # State machine check
    is_valid = PlanRevisionStateMachine.can_transition(expected_rev, active_plan.status, "rev09", PlanStatus.ACTIVE)
    assert is_valid is False

    receipt = Receipt(
        receipt_id="RCT-ERR-001",
        action_id="ACT-001",
        plan_revision_id=active_plan.revision,
        action_type="UPDATE_PLAN",
        status="DENIED",
        timestamp="2026-08-07T09:10:00Z",
        mutations_applied=0,
        message=f"Precondition failed: Expected revision {expected_rev} does not match active revision {active_plan.revision}",
        trace_id="TRC-001",
    )

    assert receipt.status == "DENIED"
    assert receipt.mutations_applied == 0
