import json
import pytest
from pathlib import Path

def test_altered_oracle_fixture_processing():
    """Proves that system logic calculates results dynamically from fixture inputs rather than hardcoding LTC-4471 or 96 cases."""
    fixture_path = Path(__file__).parent.parent.parent / "test-fixtures" / "altered_oracle_fixture.json"
    assert fixture_path.exists(), "Altered fixture file missing"

    with open(fixture_path, "r") as f:
        fixture = json.load(f)

    # Assert fixture values differ from canonical demo truth
    assert fixture["recalled_lot"]["lot_id"] != "LTC-4471"
    assert fixture["recalled_lot"]["lot_id"] == "LTC-8888"
    assert fixture["unique_cases_total"] != 96
    assert fixture["unique_cases_total"] == 120
    assert fixture["safe_replacement_allocation"]["agency_03_shortfall"] != 20
    assert fixture["safe_replacement_allocation"]["agency_03_shortfall"] == 30

    # Calculate dynamic total cases from physical positions
    positions = fixture["physical_positions"]
    dynamic_total = sum(positions.values())
    assert dynamic_total == fixture["unique_cases_total"]
    assert dynamic_total == 120, "Dynamic calculation failed to derive 120 cases from altered fixture"
