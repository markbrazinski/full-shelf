import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


orchestrator_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if orchestrator_src not in sys.path:
    sys.path.insert(0, orchestrator_src)

import main as orchestrator_main


CANONICAL_ROWS = [
    ("NODE-WAREHOUSE", "WAREHOUSE", "Main Warehouse", 24, "NODE-AGENCY-01", "AGENCY", "Agency 01", 10, 1),
    ("NODE-WAREHOUSE", "WAREHOUSE", "Main Warehouse", 24, "NODE-RESCUE", "DIRECT_RESCUE", "Rescue", 12, 1),
    ("NODE-WAREHOUSE", "WAREHOUSE", "Main Warehouse", 24, "NODE-STAGING-O203", "STAGING", "Order O203", 20, 1),
    ("NODE-WAREHOUSE", "WAREHOUSE", "Main Warehouse", 24, "NODE-TRUCK-2", "VEHICLE", "Order O202", 22, 1),
    ("NODE-WAREHOUSE", "WAREHOUSE", "Main Warehouse", 24, "NODE-SITE-01", "DOWNSTREAM_SITE", "Site 01", 8, 2),
]

ALTERED_ROWS = [
    ("ALT-WH", "WAREHOUSE", "Alternate Hub", 13, "ALT-MOVE-1", "OPERATIONAL_MOVEMENT", "Movement 701", 0, 1),
    ("ALT-WH", "WAREHOUSE", "Alternate Hub", 13, "ALT-RESCUE", "DIRECT_RESCUE", "Rescue 9", 7, 1),
    ("ALT-WH", "WAREHOUSE", "Alternate Hub", 13, "ALT-ORDER-701", "ORDER", "Order 701", 0, 2),
    ("ALT-WH", "WAREHOUSE", "Alternate Hub", 13, "ALT-ORDER-702", "ORDER", "Order 702", 0, 2),
    ("ALT-WH", "WAREHOUSE", "Alternate Hub", 13, "ALT-AGENCY-77", "AGENCY", "Agency 77", 17, 3),
    ("ALT-WH", "WAREHOUSE", "Alternate Hub", 13, "ALT-AGENCY-88", "AGENCY", "Agency 88", 9, 3),
    ("ALT-WH", "WAREHOUSE", "Alternate Hub", 13, "ALT-SITE-77", "DOWNSTREAM_SITE", "Site 77", 5, 4),
]


def _database(rows):
    db = MagicMock()
    snapshot = MagicMock()
    snapshot.execute_sql.return_value = rows
    db.snapshot.return_value.__enter__.return_value = snapshot
    return db, snapshot


def test_canonical_query_is_parameterized_multihop_gql_and_reconciles_96():
    db, snapshot = _database(CANONICAL_ROWS)

    result = orchestrator_main._run_managed_custody_graph(
        db, tenant_id="east-bay-food-bank", lot_id="LTC-4471"
    )

    query = snapshot.execute_sql.call_args.args[0]
    kwargs = snapshot.execute_sql.call_args.kwargs
    assert "GRAPH CustodyGraph" in query
    assert "]->{1,8}" in query
    assert "@tenant_id" in query
    assert "@lot_id" in query
    assert kwargs["params"] == {
        "tenant_id": "east-bay-food-bank",
        "lot_id": "LTC-4471",
    }
    assert result["unique_current_cases"] == 96
    assert result["max_path_depth"] == 2
    site = next(node for node in result["current_positions"] if node["node_id"] == "NODE-SITE-01")
    assert site["path_depth"] == 2
    assert result["intermediate_subtotals_readded"] is False


def test_altered_topology_is_calculated_from_managed_query_rows():
    db, _ = _database(ALTERED_ROWS)

    result = orchestrator_main._run_managed_custody_graph(
        db, tenant_id="wp8-altered-audit", lot_id="ALT-LOT-9001"
    )

    assert result["unique_current_cases"] == 51
    assert result["max_path_depth"] == 4
    assert result["node_count"] == 8
    assert {node["node_type"] for node in result["current_positions"]} >= {
        "OPERATIONAL_MOVEMENT", "ORDER", "AGENCY", "DOWNSTREAM_SITE"
    }


def test_managed_graph_has_no_empty_result_fallback():
    db, _ = _database([])

    with pytest.raises(LookupError, match="GRAPH_TOPOLOGY_NOT_FOUND"):
        orchestrator_main._run_managed_custody_graph(
            db, tenant_id="east-bay-food-bank", lot_id="missing"
        )


def test_altered_endpoint_uses_only_configured_audit_database():
    db, _ = _database(ALTERED_ROWS)
    client = TestClient(orchestrator_main.app)

    with (
        patch.dict(os.environ, {
            "SPANNER_DATABASE_ID": "full-shelf-main",
            "AUDIT_SPANNER_DATABASE_ID": "full-shelf-audit-wp6-20260813",
            "AUDIT_TENANT_IDS": "wp8-altered-audit",
        }),
        patch.object(orchestrator_main, "verify_judge_key"),
        patch.object(orchestrator_main, "get_spanner_database", return_value=db) as get_db,
    ):
        response = client.get("/api/v1/orchestrator/custody/graph?scenario=altered")

    assert response.status_code == 200
    assert response.json()["lot_id"] == "ALT-LOT-9001"
    assert response.json()["unique_current_cases"] == 51
    get_db.assert_called_once_with("full-shelf-audit-wp6-20260813")
