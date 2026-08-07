from typing import List, Dict
from .models import CustodyNode, CustodyEdge, HazardStatus


class RecallReconciliationResult:
    def __init__(
        self,
        recalled_lot_id: str,
        total_unique_physical_cases: int,
        node_breakdown: Dict[str, int],
        contains_sub_distribution: bool,
        sub_distributed_unconfirmed_cases: int,
        is_fully_contained: bool,
        terminal_status: str,
    ):
        self.recalled_lot_id = recalled_lot_id
        self.total_unique_physical_cases = total_unique_physical_cases
        self.node_breakdown = node_breakdown
        self.contains_sub_distribution = contains_sub_distribution
        self.sub_distributed_unconfirmed_cases = sub_distributed_unconfirmed_cases
        self.is_fully_contained = is_fully_contained
        self.terminal_status = terminal_status


def reconcile_recall_graph(
    nodes: List[CustodyNode],
    edges: List[CustodyEdge],
    recalled_lot_id: str = "LTC-4471",
    unconfirmed_subsite_ids: List[str] = None,
) -> RecallReconciliationResult:
    """
    Reconciles custody graph for recalled lot LTC-4471 without double-counting physical cases.
    
    Canonical physical positions for LTC-4471:
      - Warehouse: 24
      - Truck 2 (O202): 22
      - Pickup Staging (O203): 20
      - Agency 01: 10
      - Site 01 (Sub-distributed from Agency 01): 8
      - Direct-Rescue Recipient: 12
      Total unique physical cases = 24 + 22 + 20 + 10 + 8 + 12 = 96 cases.
      
    If Site 01 (8 cases) remains unconfirmed, is_fully_contained=False and
    terminal_status = "PARTIALLY_CONTAINED".
    """
    if unconfirmed_subsite_ids is None:
        unconfirmed_subsite_ids = []

    node_breakdown: Dict[str, int] = {}
    total_physical_cases = 0

    # Map node on-hand cases
    for node in nodes:
        node_breakdown[node.name] = node.on_hand_cases
        total_physical_cases += node.on_hand_cases

    # Count unconfirmed sub-distributed cases
    unconfirmed_cases = 0
    for edge in edges:
        if edge.is_sub_distribution and edge.target_node_id in unconfirmed_subsite_ids:
            unconfirmed_cases += edge.case_count

    is_contained = unconfirmed_cases == 0
    terminal_status = "CONTAINED" if is_contained else "PARTIALLY_CONTAINED"

    return RecallReconciliationResult(
        recalled_lot_id=recalled_lot_id,
        total_unique_physical_cases=total_physical_cases,
        node_breakdown=node_breakdown,
        contains_sub_distribution=any(e.is_sub_distribution for e in edges),
        sub_distributed_unconfirmed_cases=unconfirmed_cases,
        is_fully_contained=is_contained,
        terminal_status=terminal_status,
    )
