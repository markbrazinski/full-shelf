import pytest
from full_shelf_domain.models import CustodyNode, CustodyEdge
from full_shelf_domain.reconciliation import reconcile_recall_graph, RecallReconciliationResult


def test_primary_canonical_multihop_graph_reconciliation():
    nodes = [
        CustodyNode(node_id="N1", node_type="WAREHOUSE", name="Main Warehouse", on_hand_cases=24),
        CustodyNode(node_id="N2", node_type="VEHICLE", name="Truck 02 (O202)", on_hand_cases=22),
        CustodyNode(node_id="N3", node_type="STAGING", name="Pickup Staging (O203)", on_hand_cases=20),
        CustodyNode(node_id="N4", node_type="AGENCY", name="Agency 01", on_hand_cases=10),
        CustodyNode(node_id="N5", node_type="SUBSITE", name="Site 01", on_hand_cases=8),
        CustodyNode(node_id="N6", node_type="DIRECT_RESCUE", name="Direct-Rescue Recipient", on_hand_cases=12),
    ]

    edges = [
        CustodyEdge(edge_id="E1", edge_type="TRANSFERRED_TO", source_node_id="N1", target_node_id="N2", lot_id="LTC-4471", case_count=22, is_sub_distribution=False),
        CustodyEdge(edge_id="E2", edge_type="TRANSFERRED_TO", source_node_id="N1", target_node_id="N3", lot_id="LTC-4471", case_count=20, is_sub_distribution=False),
        CustodyEdge(edge_id="E3", edge_type="TRANSFERRED_TO", source_node_id="N1", target_node_id="N4", lot_id="LTC-4471", case_count=18, is_sub_distribution=False),
        CustodyEdge(edge_id="E4", edge_type="TRANSFERRED_TO", source_node_id="N4", target_node_id="N5", lot_id="LTC-4471", case_count=8, is_sub_distribution=True),
        CustodyEdge(edge_id="E5", edge_type="TRANSFERRED_TO", source_node_id="N1", target_node_id="N6", lot_id="LTC-4471", case_count=12, is_sub_distribution=False),
    ]

    result = reconcile_recall_graph(
        nodes=nodes,
        edges=edges,
        recalled_lot_id="LTC-4471",
        unconfirmed_subsite_ids=["N5"]
    )

    assert result.total_unique_physical_cases == 96
    assert result.contains_sub_distribution is True
    assert result.sub_distributed_unconfirmed_cases == 8
    assert result.is_fully_contained is False
    assert result.terminal_status == "PARTIALLY_CONTAINED"


def test_secondary_altered_topology_graph_reconciliation():
    nodes = [
        CustodyNode(node_id="HUB-1", node_type="WAREHOUSE", name="Central Food Hub", on_hand_cases=50),
        CustodyNode(node_id="DEPOT-A", node_type="STAGING", name="North Depot", on_hand_cases=40),
        CustodyNode(node_id="AG-10", node_type="AGENCY", name="Community Pantry 10", on_hand_cases=30),
        CustodyNode(node_id="AG-11", node_type="AGENCY", name="Community Pantry 11", on_hand_cases=20),
        CustodyNode(node_id="SITE-99", node_type="SUBSITE", name="Subsite 99", on_hand_cases=10),
    ]

    edges = [
        CustodyEdge(edge_id="EDGE-1", edge_type="TRANSFERRED_TO", source_node_id="HUB-1", target_node_id="DEPOT-A", lot_id="LTC-8899", case_count=100, is_sub_distribution=False),
        CustodyEdge(edge_id="EDGE-2", edge_type="TRANSFERRED_TO", source_node_id="DEPOT-A", target_node_id="AG-10", lot_id="LTC-8899", case_count=40, is_sub_distribution=False),
        CustodyEdge(edge_id="EDGE-3", edge_type="TRANSFERRED_TO", source_node_id="DEPOT-A", target_node_id="AG-11", lot_id="LTC-8899", case_count=20, is_sub_distribution=False),
        CustodyEdge(edge_id="EDGE-4", edge_type="SUB_DISTRIBUTED", source_node_id="AG-10", target_node_id="SITE-99", lot_id="LTC-8899", case_count=10, is_sub_distribution=True),
    ]

    result = reconcile_recall_graph(
        nodes=nodes,
        edges=edges,
        recalled_lot_id="LTC-8899",
        unconfirmed_subsite_ids=[]
    )

    assert result.recalled_lot_id == "LTC-8899"
    assert result.total_unique_physical_cases == 150
    assert result.contains_sub_distribution is True
    assert result.sub_distributed_unconfirmed_cases == 0
    assert result.is_fully_contained is True
    assert result.terminal_status == "CONTAINED"
