import json
from pathlib import Path

from full_shelf_domain.ledger_commands import OperatingPlanDefinition


ROOT = Path(__file__).resolve().parents[3]


def _fixture(name):
    return json.loads((ROOT / "test-fixtures" / name).read_text())


def test_canonical_shaped_fixture_is_contract_valid_and_preserves_locked_truth():
    fixture = _fixture("audit_canonical_shaped.json")
    plan = OperatingPlanDefinition.model_validate(fixture["operating_plan"])

    assert sum(node.on_hand_cases for node in plan.custody_nodes) == 96
    assert sum(
        node.on_hand_cases for node in plan.custody_nodes
        if node.acknowledgment_status == "UNCONFIRMED"
    ) == 8
    assert sum(lot.total_cases for lot in plan.lots if lot.hazard_status == "CLEAR_SAFE") == 40


def test_altered_fixture_is_contract_valid_and_materially_different():
    fixture = _fixture("audit_altered.json")
    plan = OperatingPlanDefinition.model_validate(fixture["operating_plan"])

    assert {lot.lot_id for lot in plan.lots} == {"ALT-8842", "SAFE-9200"}
    assert sum(node.on_hand_cases for node in plan.custody_nodes) == 51
    assert len(plan.custody_edges) == 7
    assert sum(
        node.on_hand_cases for node in plan.custody_nodes
        if node.acknowledgment_status == "UNCONFIRMED"
    ) == 5
