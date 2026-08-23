"""Read-only tool adapters and deterministic generators for the ADK fleet.

Every function here is a pure read or a pure computation over data the caller
already read under its own authority. Nothing in this module opens a client,
performs I/O, or mutates state; the orchestrator passes snapshots in.

Exact arithmetic, capacity, graph counts, deduplication, and candidate contents
are owned here and never by a model. Agents may only read these results.

ADK-visible tools are built by `build_*_tool` factories, which return named,
typed, documented `FunctionTool` objects whose runtime names equal the stable
catalog tool IDs' local names. No anonymous lambda is ever exposed to a model.
"""

import hashlib
from typing import Any, Dict, List, Optional, Sequence

from .contracts import (
    TOOL_CUSTODY_DEPENDENTS_READ,
    TOOL_CUSTODY_GRAPH_READ,
    TOOL_PARTNER_STATE_READ,
    TOOL_RECOVERY_CANDIDATES_READ,
    TOOL_RUNTIME_NAMES,
)


def custody_graph_read(graph_result: Dict[str, Any]) -> Dict[str, Any]:
    """Project an already-executed Spanner Graph result into agent-safe facts.

    The projection is narrowing only: it drops the raw GQL text and query
    parameters so no prompt can carry query shape, and restates the counts the
    managed query already computed.
    """
    positions = graph_result.get("current_positions", [])
    return {
        "tool_id": TOOL_CUSTODY_GRAPH_READ,
        "tool_outcome": "OK",
        "lot_id": graph_result.get("lot_id"),
        "query_engine": graph_result.get("query_engine", "SPANNER_GRAPH_GQL"),
        "total_cases_in_custody": graph_result["unique_current_cases"],
        "confirmed_cases": graph_result["confirmed_cases"],
        "unconfirmed_cases": graph_result["unconfirmed_cases"],
        "unconfirmed_node_ids": [
            position["node_id"] for position in graph_result["unconfirmed_positions"]
        ],
        "max_path_depth": graph_result.get("max_path_depth"),
        "node_count": graph_result.get("node_count", len(positions)),
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
        "intermediate_subtotals_readded": graph_result.get(
            "intermediate_subtotals_readded", False
        ),
    }


def custody_dependents_read(
    graph_result: Dict[str, Any], *, node_id: str
) -> Dict[str, Any]:
    """Return the deterministic downstream dependents of one custody node."""
    paths = [
        path for path in graph_result.get("paths", [])
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
        for position in graph_result.get("current_positions", [])
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


# The deterministic candidate policy is exactly these two safe-lot consumption
# orderings. This is a BOUNDED policy, not an exhaustive search of all feasible
# allocations, and the catalog states it as such.
CANDIDATE_POLICY_ID = "full-shelf.policy.bounded-lot-ordering.v1"
CANDIDATE_POLICY_ORDERINGS = ("CAND-LOT-ASC", "CAND-LOT-DEEPEST-FIRST")


def generate_recovery_candidates(
    *,
    incident_id: str,
    safe_lots: Sequence[Sequence],
    affected_orders: Sequence[Sequence],
) -> List[Dict[str, Any]]:
    """Build the candidate set defined by the bounded lot-ordering policy.

    This is NOT a complete enumeration of every feasible allocation. The policy
    admits exactly two safe-lot consumption orderings:

    * `CAND-LOT-ASC` reproduces the accepted lot-ascending allocation exactly,
      so the canonical result is unchanged.
    * `CAND-LOT-DEEPEST-FIRST` consumes the largest safe lot first.

    Distinct candidates are deduplicated by allocation content, so a scenario
    with only one truthful outcome yields exactly one candidate and the planner
    has no discretion to exercise.
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
        "candidate_policy_id": CANDIDATE_POLICY_ID,
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


# ---------------------------------------------------------------------------
# ADK-visible tool factories.
#
# Each factory closes over already-read deterministic data and returns a NAMED,
# typed, documented function wrapped in an ADK FunctionTool. The runtime tool
# name is asserted against TOOL_RUNTIME_NAMES so the model-visible name can
# never drift from the governed catalog ID.
# ---------------------------------------------------------------------------


def _as_function_tool(func, expected_name: str):
    """Wrap a named adapter in an ADK FunctionTool and pin its runtime name."""
    from google.adk.tools import FunctionTool

    if func.__name__ != expected_name:
        raise ValueError(
            f"TOOL_RUNTIME_NAME_MISMATCH: {func.__name__} != {expected_name}"
        )
    tool = FunctionTool(func)
    if tool.name != expected_name:
        raise ValueError(f"ADK_TOOL_NAME_MISMATCH: {tool.name} != {expected_name}")
    return tool


def build_custody_graph_tool(graph_result: Dict[str, Any]):
    """Build the ADK tool exposing `TOOL_CUSTODY_GRAPH_READ`."""

    def custody_graph_read_tool() -> Dict[str, Any]:
        """Read the authoritative custody reconstruction for the recalled lot.

        Returns total, confirmed, and unconfirmed case counts, the unconfirmed
        node IDs, the maximum path depth, and every current custody position.
        All values are computed by Spanner Graph, not by this tool.
        """
        return custody_graph_read(graph_result)

    return _as_function_tool(
        custody_graph_read_tool, TOOL_RUNTIME_NAMES[TOOL_CUSTODY_GRAPH_READ]
    )


def build_custody_dependents_tool(graph_result: Dict[str, Any]):
    """Build the ADK tool exposing `TOOL_CUSTODY_DEPENDENTS_READ`."""

    def custody_dependents_read_tool(node_id: str) -> Dict[str, Any]:
        """Read the downstream custody dependents of one node.

        Args:
          node_id: The custody node identifier to inspect.

        Returns each dependent node's ID, path depth, on-hand cases, and
        acknowledgment status, or NOT_FOUND when the node has no paths.
        """
        return custody_dependents_read(graph_result, node_id=node_id)

    return _as_function_tool(
        custody_dependents_read_tool,
        TOOL_RUNTIME_NAMES[TOOL_CUSTODY_DEPENDENTS_READ],
    )


def build_recovery_candidates_tool(candidates: Sequence[Dict[str, Any]]):
    """Build the ADK tool exposing `TOOL_RECOVERY_CANDIDATES_READ`."""

    def recovery_candidates_read_tool() -> Dict[str, Any]:
        """Read the deterministic recovery candidates you may choose among.

        Returns each candidate's ID, strategy, allocated and shortfall case
        totals, agencies served, and exact allocations. You may select only a
        candidate_id from this set; you may not modify any value inside it.
        """
        return recovery_candidates_read(candidates)

    return _as_function_tool(
        recovery_candidates_read_tool,
        TOOL_RUNTIME_NAMES[TOOL_RECOVERY_CANDIDATES_READ],
    )


def build_partner_state_tool(partner_state: Dict[str, Any]):
    """Build the ADK tool exposing `TOOL_PARTNER_STATE_READ`."""

    def partner_state_read_tool() -> Dict[str, Any]:
        """Read the bounded operational state of the partner to contact.

        Returns the partner ID and name, the recalled lot, the unconfirmed case
        count, the acknowledgment status, and the deadline when one exists.
        Every outbound template parameter must be copied from these values.
        """
        return dict(partner_state)

    return _as_function_tool(
        partner_state_read_tool, TOOL_RUNTIME_NAMES[TOOL_PARTNER_STATE_READ]
    )
