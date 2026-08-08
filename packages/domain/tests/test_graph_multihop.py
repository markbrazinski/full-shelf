import pytest
from full_shelf_domain.models import CustodyNode, CustodyEdge
from full_shelf_domain.reconciliation import reconcile_recall_graph, RecallReconciliationResult


def test_primary_canonical_multihop_graph_reconciliation():
    nodes = [
        CustodyNode("N1", "WAREHOUSE", "Main Warehouse", 24),
        CustodyNode("N2", "VEHICLE", "Truck 02 (O202)", 22),
        CustodyNode("N3", "STAGING", "Pickup Staging (O203)", 20),
        CustodyNode("N4", "AGENCY", "Agency 01", 10),
        CustodyNode("N5", "SUBSITE", "Site 01", 8),
        CustodyNode("N6", "RESCUE", "Direct-Rescue Recipient", 12),
    ]

    edges = [
        CustodyEdge("E1", "TRANSFERRED_TO", "N1", "N2", 22, False),
        CustodyEdge("E2", "TRANSFERRED_TO", "N1", "N3", 20, False),
        CustodyEdge("E3", "TRANSFERRED_TO", "N1", "N4", 18, False),
        CustodyEdge("E4", "TRANSFERRED_TO", "N4", "N5", 8, True),
        CustodyEdge("E5", "TRANSFERRED_TO", "N1", "N6", 12, False),
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
    # Second scenario with different Lot ID, transfer depth, agency layout, and case quantities
    nodes = [
        CustodyNode("HUB-1", "CENTRAL_HUB", "Central Food Hub", 50),
        CustodyNode("DEPOT-A", "REGIONAL_DEPOT", "North Depot", 40),
        CustodyNode("AG-10", "AGENCY", "Community Pantry 10", 30),
        CustodyNode("AG-11", "AGENCY", "Community Pantry 11", 20),
        CustodyNode("SITE-99", "DISTRIBUTION_SITE", "Subsite 99", 10),
    ]

    edges = [
        CustodyEdge("EDGE-1", "TRANSFERRED_TO", "HUB-1", "DEPOT-A", 100, False),
        CustodyEdge("EDGE-2", "TRANSFERRED_TO", "DEPOT-A", "AG-10", 40, False),
        CustodyEdge("EDGE-3", "TRANSFERRED_TO", "DEPOT-A", "AG-11", 20, False),
        CustodyEdge("EDGE-4", "SUB_DISTRIBUTED", "AG-10", "SITE-99", 10, True),
    ]

    result = reconcile_recall_graph(
        nodes=nodes,
        edges=edges,
        recalled_lot_id="LTC-8899",
        unconfirmed_subsite_ids=[]  # fully confirmed
    )

    assert result.recalled_lot_id == "LTC-8899"
    assert result.total_unique_physical_cases == 150
    assert result.contains_sub_distribution is True
    assert result.sub_distributed_unconfirmed_cases == 0
    assert result.is_fully_contained is True
    assert result.terminal_status == "CONTAINED"
