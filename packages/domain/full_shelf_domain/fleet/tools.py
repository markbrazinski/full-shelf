"""Read-only tool adapters and deterministic generators for the ADK fleet.

Every function here is a pure read or a pure computation over data the caller
already read under its own authority. Nothing in this module opens a client,
performs I/O, or mutates state; the orchestrator passes snapshots in.

Exact arithmetic, capacity, graph counts, deduplication, and candidate contents
are owned here and never by a model. Agents may only read these results.
"""

import hashlib
from typing import Any, Dict, List, Optional, Sequence

from .contracts import (
    TOOL_CUSTODY_DEPENDENTS_READ,
    TOOL_CUSTODY_GRAPH_READ,
    TOOL_PARTNER_STATE_READ,
    TOOL_RECOVERY_CANDIDATES_READ,
)


def custody_graph_read(graph_result: Dict[str, Any]) -> Dict[str, Any]:
    """Project an already-executed Spanner Graph result into agent-safe facts.

    The projection is narrowing only: it drops the raw GQL text and query
    parameters so no prompt can carry query shape, and restates the counts the
    managed query already computed.
    """
    positions = graph_result["current_positions"]
    return {
        "tool_id": TOOL_CUSTODY_GRAPH_READ,
        "tool_outcome": "OK",
        "lot_id": graph_result["lot_id"],
        "query_engine": graph_result["query_engine"],
        "total_cases_in_custody": graph_result["unique_current_cases"],
        "confirmed_cases": graph_result["confirmed_cases"],
        "unconfirmed_cases": graph_result["unconfirmed_cases"],
        "unconfirmed_node_ids": [
            position["node_id"] for position in graph_result["unconfirmed_positions"]
        ],
        "max_path_depth": graph_result["max_path_depth"],
        "node_count": graph_result["node_count"],
        "positions": [
            {
                "node_id": position["node_id"],
                "node_type": position["node_type"],
                "name": position["name"],
                "on_hand_cases": position["on_hand_cases"],
                "acknowledgment_status": position["acknowledgment_status"],
                "path_depth": position["path_depth"],
            }
            for position in positions
        ],
        "intermediate_subtotals_readded": graph_result["intermediate_subtotals_readded"],
    }


def custody_dependents_read(
    graph_result: Dict[str, Any], *, node_id: str
) -> Dict[str, Any]:
    """Return the deterministic downstream dependents of one custody node."""
    paths = [
        path for path in graph_result["paths"]
        if path["root_node_id"] == node_id or path["destination_node_id"] == node_id
    ]
    if not paths:
        return {
            "tool_id": TOOL_CUSTODY_DEPENDENTS_READ,
            "tool_outcome": "NOT_FOUND",
            "node_id": node_id,
            "dependents": [],
        }
    by_id = {
        position["node_id"]: position
        for position in graph_result["current_positions"]
    }
    dependents = [
        {
            "node_id": path["destination_node_id"],
            "path_depth": path["path_depth"],
            "on_hand_cases": by_id.get(path["destination_node_id"], {}).get(
                "on_hand_cases"
            ),
            "acknowledgment_status": by_id.get(path["destination_node_id"], {}).get(
                "acknowledgment_status"
            ),
        }
        for path in paths
        if path["destination_node_id"] != node_id
    ]
    return {
        "tool_id": TOOL_CUSTODY_DEPENDENTS_READ,
        "tool_outcome": "OK",
        "node_id": node_id,
        "dependents": sorted(dependents, key=lambda d: (d["path_depth"], d["node_id"])),
    }


def _allocation_id(incident_id: str, agency_id: str, lot_id: str) -> str:
    digest = hashlib.sha256(
        f"{incident_id}\x00{agency_id}\x00{lot_id}".encode()
    ).hexdigest()[:20].upper()
    return f"ALLOC-{digest}"


def _shortfall_id(incident_id: str, agency_id: str, order_id: str) -> str:
    digest = hashlib.sha256(
        f"{incident_id}\x00{agency_id}\x00{order_id}".encode()
    ).hexdigest()[:20].upper()
    return f"SHORT-{digest}"


def _plan_from_lot_order(
    *,
    incident_id: str,
    safe_lots: Sequence[Sequence],
    affected_orders: Sequence[Sequence],
    lot_order: Sequence[str],
) -> Optional[Dict[str, Any]]:
    """Allocate affected orders against safe lots consumed in `lot_order`.

    Returns None when the ordering yields no allocation or no shortfall, which
    would violate the accepted partial-recovery policy.
    """
    available = {row[0]: row[1] for row in safe_lots}
    if set(lot_order) != set(available):
        return None
    remaining = [[lot_id, available[lot_id]] for lot_id in lot_order]
    allocations: List[Dict[str, Any]] = []
    shortfalls: List[Dict[str, Any]] = []
    for order_id, agency_id, cases in affected_orders:
        unmet = cases
        for safe_lot in remaining:
            if unmet == 0:
                break
            assigned = min(unmet, safe_lot[1])
            if assigned <= 0:
                continue
            allocations.append({
                "allocation_id": _allocation_id(incident_id, agency_id, safe_lot[0]),
                "agency_id": agency_id,
                "lot_id": safe_lot[0],
                "cases": assigned,
            })
            safe_lot[1] -= assigned
            unmet -= assigned
        if unmet:
            shortfalls.append({
                "shortfall_id": _shortfall_id(incident_id, agency_id, order_id),
                "agency_id": agency_id,
                "cases": unmet,
            })
    if not allocations or not shortfalls:
        return None
    return {"allocations": allocations, "shortfalls": shortfalls}


def _candidate_hash(candidate: Dict[str, Any]) -> str:
    payload = "|".join(
        f"{a['agency_id']}:{a['lot_id']}:{a['cases']}" for a in candidate["allocations"]
    ) + "#" + "|".join(
        f"{s['agency_id']}:{s['cases']}" for s in candidate["shortfalls"]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def generate_recovery_candidates(
    *,
    incident_id: str,
    safe_lots: Sequence[Sequence],
    affected_orders: Sequence[Sequence],
) -> List[Dict[str, Any]]:
    """Build the complete deterministic feasible candidate set.

    Candidate 1 (`CAND-LOT-ASC`) reproduces the accepted lot-ascending policy
    exactly, so the canonical result is unchanged. Additional candidates come
    from other truthful safe-lot consumption orders that still satisfy the
    partial-recovery policy. Distinct candidates are deduplicated by allocation
    content, so a scenario with only one truthful outcome yields exactly one
    candidate and the planner has no discretion to exercise.

    ponytail: two orderings (ascending, descending by remaining stock) cover the
    real choice; a full permutation search buys nothing until a scenario has
    more than a handful of safe lots.
    """
    lot_ids = [row[0] for row in safe_lots]
    orderings = [
        ("CAND-LOT-ASC", "Consume safe lots in ascending lot order",
         sorted(lot_ids)),
        ("CAND-LOT-DEEPEST-FIRST", "Consume the largest safe lot first",
         [row[0] for row in sorted(safe_lots, key=lambda r: (-r[1], r[0]))]),
    ]

    candidates: List[Dict[str, Any]] = []
    seen_hashes = set()
    for candidate_id, strategy, lot_order in orderings:
        plan = _plan_from_lot_order(
            incident_id=incident_id, safe_lots=safe_lots,
            affected_orders=affected_orders, lot_order=lot_order,
        )
        if plan is None:
            continue
        candidate = {
            "candidate_id": candidate_id,
            "strategy": strategy,
            "lot_consumption_order": list(lot_order),
            "allocations": plan["allocations"],
            "shortfalls": plan["shortfalls"],
            "total_allocated_cases": sum(a["cases"] for a in plan["allocations"]),
            "total_shortfall_cases": sum(s["cases"] for s in plan["shortfalls"]),
            "distinct_agencies_served": len(
                {a["agency_id"] for a in plan["allocations"]}
            ),
        }
        content_hash = _candidate_hash(candidate)
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        candidate["content_hash"] = content_hash
        candidates.append(candidate)
    return candidates


def recovery_candidates_read(candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Project candidates for the planner agent without exposing mutable state."""
    return {
        "tool_id": TOOL_RECOVERY_CANDIDATES_READ,
        "tool_outcome": "OK" if candidates else "EMPTY",
        "candidate_ids": [c["candidate_id"] for c in candidates],
        "candidates": [
            {
                "candidate_id": c["candidate_id"],
                "strategy": c["strategy"],
                "total_allocated_cases": c["total_allocated_cases"],
                "total_shortfall_cases": c["total_shortfall_cases"],
                "distinct_agencies_served": c["distinct_agencies_served"],
                "allocations": c["allocations"],
                "shortfalls": c["shortfalls"],
            }
            for c in candidates
        ],
    }


def partner_state_read(
    *,
    partner_id: str,
    partner_name: str,
    lot_id: str,
    unconfirmed_cases: int,
    acknowledgment_status: str,
    deadline: Optional[str] = None,
) -> Dict[str, Any]:
    """Project bounded partner state. No free text leaves this function."""
    return {
        "tool_id": TOOL_PARTNER_STATE_READ,
        "tool_outcome": "OK",
        "partner_id": partner_id,
        "partner_name": partner_name,
        "lot_id": lot_id,
        "unconfirmed_cases": unconfirmed_cases,
        "acknowledgment_status": acknowledgment_status,
        "deadline": deadline,
    }
