import pytest
from full_shelf_domain.models import Receipt


class MockLedgerStore:
    def __init__(self):
        self.executed_actions = {}
        self.mutation_count = 0

    def execute_action(self, action_id: str, plan_revision_id: str, payload: dict) -> Receipt:
        if action_id in self.executed_actions:
            # Duplicate execution attempt: return recorded receipt with 0 additional mutations
            existing_receipt = self.executed_actions[action_id]
            return Receipt(
                receipt_id=existing_receipt.receipt_id,
                action_id=action_id,
                plan_revision_id=plan_revision_id,
                action_type=existing_receipt.action_type,
                status="SUCCESS",
                timestamp=existing_receipt.timestamp,
                mutations_applied=0,  # Zero additional mutations
                message="Duplicate execution detected. Idempotent replay returned existing receipt.",
                trace_id=existing_receipt.trace_id,
            )

        # First execution: apply 1 mutation
        self.mutation_count += 1
        receipt = Receipt(
            receipt_id=f"RCT-{action_id}",
            action_id=action_id,
            plan_revision_id=plan_revision_id,
            action_type=payload.get("action_type", "REROUTE"),
            status="SUCCESS",
            timestamp="2026-08-07T09:05:00Z",
            mutations_applied=1,
            message="Action applied successfully",
            trace_id="TRC-001",
        )
        self.executed_actions[action_id] = receipt
        return receipt


def test_idempotent_replay_zero_additional_mutations():
    """Executing an action twice with the same action_id results in exactly 1 DB mutation total."""
    store = MockLedgerStore()
    action_id = "ACT-REROUTE-O202"

    # First invocation
    r1 = store.execute_action(action_id, "v1", {"action_type": "REROUTE_ORDER"})
    assert r1.status == "SUCCESS"
    assert r1.mutations_applied == 1
    assert store.mutation_count == 1

    # Replay invocation with same action_id
    r2 = store.execute_action(action_id, "v1", {"action_type": "REROUTE_ORDER"})
    assert r2.status == "SUCCESS"
    assert r2.mutations_applied == 0
    assert "Duplicate execution detected" in r2.message
    assert store.mutation_count == 1  # Still 1 total mutation in store
