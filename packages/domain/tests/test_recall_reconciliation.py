import pytest
from full_shelf_domain.models import CustodyNode, CustodyEdge, NodeType
from full_shelf_domain.reconciliation import reconcile_recall_graph


def test_recall_reconciliation_96_unique_cases():
    """
    Verifies 96 unique physical cases for LTC-4471:
      Warehouse: 24
      Truck 2: 22
      Pickup Staging: 20
      Agency 01: 10
      Site 01: 8
      Direct Rescue: 12
      Sum = 96 unique cases.
    """
    nodes = [
        CustodyNode(node_id="N-WH", node_type=NodeType.WAREHOUSE, name="Warehouse", on_hand_cases=24),
        CustodyNode(node_id="N-TR2", node_type=NodeType.VEHICLE, name="Truck 2", on_hand_cases=22),
        CustodyNode(node_id="N-STG", node_type=NodeType.STAGING, name="Pickup Staging", on_hand_cases=20),
        CustodyNode(node_id="N-AG01", node_type=NodeType.AGENCY, name="Agency 01", on_hand_cases=10),
        CustodyNode(node_id="N-ST01", node_type=NodeType.SUBSITE, name="Site 01", on_hand_cases=8),
        CustodyNode(node_id="N-RESC", node_type=NodeType.DIRECT_RESCUE, name="Direct Rescue", on_hand_cases=12),
    ]

    edges = [
        CustodyEdge(
            edge_id="E-01",
            source_node_id="N-AG01",
            target_node_id="N-ST01",
            lot_id="LTC-4471",
            case_count=8,
            is_sub_distribution=True,
        )
    ]

    # Site 01 (8 cases) unconfirmed
    res = reconcile_recall_graph(nodes, edges, "LTC-4471", unconfirmed_subsite_ids=["N-ST01"])

    assert res.total_unique_physical_cases == 96
    assert res.sub_distributed_unconfirmed_cases == 8
    assert res.is_fully_contained is False
    assert res.terminal_status == "PARTIALLY_CONTAINED"
    assert res.node_breakdown["Warehouse"] == 24
    assert res.node_breakdown["Truck 2"] == 22
    assert res.node_breakdown["Pickup Staging"] == 20
    assert res.node_breakdown["Agency 01"] == 10
    assert res.node_breakdown["Site 01"] == 8
    assert res.node_breakdown["Direct Rescue"] == 12
