import pytest
from full_shelf_domain.recall import IncidentLifecycleManager


def test_valid_lifecycle_transitions():
    assert IncidentLifecycleManager.validate_transition("DETECTED", "SCOPING") is True
    assert IncidentLifecycleManager.validate_transition("SCOPING", "CONTAINMENT_IN_PROGRESS") is True
    assert IncidentLifecycleManager.validate_transition("CONTAINMENT_IN_PROGRESS", "PARTIALLY_CONTAINED") is True


def test_refuse_contained_transition_when_unconfirmed_downstream():
    with pytest.raises(ValueError, match="DOWNSTREAM_CUSTODY_UNCONFIRMED"):
        IncidentLifecycleManager.validate_transition("PARTIALLY_CONTAINED", "CONTAINED", has_unconfirmed_downstream=True)


def test_invalid_skipping_lifecycle_transition():
    with pytest.raises(ValueError, match="Invalid transition path"):
        IncidentLifecycleManager.validate_transition("DETECTED", "PARTIALLY_CONTAINED")
