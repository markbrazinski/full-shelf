"""Truthful bounded-projection regression suite (Delta 1/2/3).

Every test drives the real handler against a faked Spanner snapshot. No managed
service, no canonical database, and no cloud state is touched: conftest.py
already points any accidental client construction at an isolated audit database.

The suite proves the four owner amendments:
  A1 timeless current-state rows are omitted when a later mutation exists;
  A2 receipts are matched by recomputed action_id, never by action_type alone;
  A3 obligations are evaluated open-as-of, not present-day-open;
  A4 Healthy carries no capacity claim, Truck Failure keeps the full proof.
"""

import hashlib
import json as _json
import os
import pathlib as _pathlib
import sys
from urllib.parse import quote
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

orchestrator_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if orchestrator_src not in sys.path:
    sys.path.insert(0, orchestrator_src)

import main as orchestrator_main  # noqa: E402


TENANT = "east-bay-food-bank"
DAY = "2026-08-14"
PLAN = f"PLAN-{DAY}"
NEXT_PLAN = "PLAN-2026-08-15"
RECALL_INC = "INC-2231"
TRUCK_INC = "INC-2210"
CORRELATION = "0123456789abcdef0123456789abcdef"


def T(hh, mm):
    return datetime(2026, 8, 14, hh, mm, tzinfo=timezone.utc)


def action_id(incident_id, action):
    digest = hashlib.sha256(
        f"{TENANT}\x00{incident_id}\x00{action}".encode("utf-8")
    ).hexdigest()
    return f"CMD-{digest[:28].upper()}"


def receipt(action, incident_id, action_type, ts, status="SUCCESS", mutations=1):
    # Receipt ids are synthetic execution evidence, so they carry the fixture-
    # prefix. Canonical business identity (INC-, PLAN-, LTC-, order/agency ids)
    # is deliberately NOT prefixed: those are the real domain values.
    return (f"fixture-RCT-{action}", action_id(incident_id, action), action_type,
            status, mutations, ts)


# Canonical Friday receipt ledger, in real commit order.
ALL_RECEIPTS = [
    receipt("plan:rev07", TRUCK_INC, "SAVE_PLAN_REVISION", T(7, 30)),
    receipt("status:SCOPING", TRUCK_INC, "SET_INCIDENT_STATUS", T(8, 20)),
    receipt("plan:rev08", TRUCK_INC, "SAVE_PLAN_REVISION", T(8, 24)),
    receipt("status:SCOPING", RECALL_INC, "SET_INCIDENT_STATUS", T(9, 36)),
    receipt("movement-barrier", RECALL_INC, "ACTIVATE_MOVEMENT_BARRIER", T(10, 5)),
    receipt("status:CONTAINMENT_IN_PROGRESS", RECALL_INC, "SET_INCIDENT_STATUS", T(10, 6)),
    receipt("plan:invalidate", RECALL_INC, "INVALIDATE_PLAN", T(10, 7)),
    receipt("safe-recovery", RECALL_INC, "ALLOCATE_SAFE_STOCK", T(10, 10)),
    receipt("containment-refusal", RECALL_INC, "RECORD_REFUSAL", T(10, 12),
            status="DENIED", mutations=0),
    receipt("status:PARTIALLY_CONTAINED", RECALL_INC, "SET_INCIDENT_STATUS", T(10, 13)),
]


def partner_receipt(source_event_id, ts, status, domain_mutations):
    return (
        f"fixture-RCT-{source_event_id}",
        f"fixture-CMD-{source_event_id}",
        "PROCESS_PARTNER_EVIDENCE",
        status,
        domain_mutations,
        ts,
    )

def _hop(agent_id, slug, validation, *, model="gemini-flash-latest",
         declared_tools=(), tool_invocations=()):
    """One persisted delegation hop, shaped exactly as the coordinator writes it."""
    return {
        "agent_id": agent_id,
        "coordinator_agent_id": "full-shelf.incident-coordinator.v1",
        "coordination_run_id": "fixture-run-coord-1",
        "agent_name": slug,
        "model_used": model,
        "adk_framework": "google-adk-2.6.1",
        "specialist_run_id": f"fixture-run-{slug}-1",
        "specialist_session_id": f"fixture-sess-{slug}-1",
        "adk_event_id": f"fixture-evt-{slug}-1",
        "declared_tools": list(declared_tools),
        "tool_invocations": list(tool_invocations),
        "deterministic_validation": validation,
    }


# A completed fleet run persists one hop per governed specialist. Only Network
# & Custody holds tools, so only it carries tool invocations.
FLEET = {
    "manifest_version": "1.1.0",
    "root_agent_id": "full-shelf.incident-coordinator.v1",
    "coordinator_session_id": "fixture-sess-coord-1",
    "coordination_run_id": "fixture-run-coord-1",
    "proposal_status": "PROPOSED",
    "proposal_hash": "abc123",
    "delegation_trace": [
        _hop("full-shelf.incident-lead.v1", "incident",
             "INCIDENT_SCOPE_DETERMINED"),
        _hop("full-shelf.recall-intake-extraction.v2", "recall",
             "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED"),
        _hop("full-shelf.network-custody.v2", "custody",
             "RECONCILED_WITH_DETERMINISTIC_GRAPH",
             declared_tools=["custody_graph_read", "custody_dependents_read"],
             tool_invocations=[{"tool_name": "custody_graph_read",
                                "status": "SUCCEEDED"}]),
        _hop("full-shelf.fulfillment-planning-recovery.v2", "recovery",
             "CANDIDATE_ID_RESOLVED_DETERMINISTICALLY"),
        _hop("full-shelf.partner-operations.v2", "partner",
             "TEMPLATE_AND_PARAMETERS_VALIDATED"),
    ],
}

# ---------------------------------------------------------------------------
# Canonical oracle.
#
# Every factual row below is derived from the tracked canonical seed fixtures
# and docs/authority/resolved-baseline.md, never from the projection's own
# output. The seeds are loaded rather than transcribed so this oracle cannot
# drift away from the authority it claims to reproduce.
#
# Canonical facts this pins (resolved-baseline.md):
#   custody 24+22+20+10+8+12 = 96 unique, 88 confirmed, 8 unconfirmed at Site 01
#   Truck 2: capacity 60, existing load 36, absorbs O202's 22 only -> 58
#   O203's 20 cases become refrigerated partner pickup, NOT a truck reroute
#   recovery replaces 40: Agency 01 = 18, Agency 02 = 22; Agency 03 short 20
#   Agency 01's historical 18-case receipt is not its current position (10);
#   Site 01's 8 cases are downstream of Agency 01.
# ---------------------------------------------------------------------------

SEEDS = _pathlib.Path(__file__).resolve().parents[3] / "packages/test-fixtures"
MORNING_PLAN = _json.loads((SEEDS / "morning_plan.json").read_text())
TRUCK_BREAKDOWN = _json.loads((SEEDS / "truck_breakdown.json").read_text())
LETTUCE_RECALL = _json.loads((SEEDS / "lettuce_recall.json").read_text())

CANONICAL_ORDERS = {o["order_id"]: o for o in MORNING_PLAN["orders"]}
CANONICAL_APPROVAL = TRUCK_BREAKDOWN["repaired_plan"]["approval"]
CANONICAL_CAPACITY = TRUCK_BREAKDOWN["capacity_check"]

# The KMS-bound diff is the canonical approval itself: O202 rerouted to Truck 2,
# O203 converted to partner pickup. Read from the seed so the pickup order and
# its case count cannot be silently substituted.
APPROVAL_DIFF = _json.dumps({
    "reroute_order_id": CANONICAL_APPROVAL["reroute_order_id"],
    "reroute_cases": CANONICAL_APPROVAL["reroute_cases"],
    "reroute_target_vehicle": CANONICAL_APPROVAL["reroute_target_vehicle"],
    "pickup_order_id": CANONICAL_APPROVAL["pickup_order_id"],
    "pickup_cases": CANONICAL_APPROVAL["pickup_cases"],
})
APPROVAL_ROWS = [(
    "fixture-APR-rev08", PLAN,
    CANONICAL_APPROVAL["source_revision"], CANONICAL_APPROVAL["proposed_revision"],
    "fixture-diffhash-rev08",
    "projects/p/locations/l/keyRings/k/cryptoKeys/c/cryptoKeyVersions/1",
    T(8, 24), APPROVAL_DIFF, "operator@example.com", f"{TENANT}@{DAY}", T(20, 0),
)]

PLAN_ROWS = [
    (PLAN, "rev07", "SUPERSEDED", T(7, 30)),
    (PLAN, "rev08", "ACTIVE", T(8, 24)),
]
NEXT_DAY_ROWS = [(NEXT_PLAN, "rev01", "DRAFT_WITH_CONSTRAINTS", T(17, 0))]

# Candidate child Orders of the Saturday draft, as the ledger committed them.
# Same row shape as ORDER_ROWS plus the agency id the candidate query reads:
# (revision, order_id, agency_name, cases, lot, vehicle, status, agency_id)
# Agency 03's 20 cases are deliberately absent: they remain unassigned demand.
CANDIDATE_ORDER_ROWS = [
    ("rev01", f"CAND-{NEXT_PLAN}-SF-A01", "Agency 01", 18, "LTC-5090",
     "TRUCK-02", "CANDIDATE", "AGENCY-01"),
    ("rev01", f"CAND-{NEXT_PLAN}-SF-A02", "Agency 02", 22, "LTC-5090",
     "TRUCK-02", "CANDIDATE", "AGENCY-02"),
]

# Agency 03's carried 20-case obligation, persisted as a visible draft
# constraint rather than absorbed into a candidate assignment.
CANDIDATE_UNASSIGNED_ROW = (
    NEXT_PLAN, "UNASSIGNED_DEMAND", "AGENCY-03", T(17, 0),
    _json.dumps({"shortfall_id": "SF-A03", "agency_id": "AGENCY-03",
                 "cases": 20,
                 "reason": "NO_CONFIRMED_SAFE_LOT_WITH_SUFFICIENT_CASES"},
                sort_keys=True),
)


def _order_row(revision, order_id, vehicle_id, status="PLANNED"):
    """One Orders row built from the canonical morning-plan seed."""
    order = CANONICAL_ORDERS[order_id]
    return (revision, order_id, order["destination_agency_name"], order["cases"],
            order["lot_id"], vehicle_id, status)


# rev07 is the morning plan as seeded. rev08 is the approved repair: O202 moves
# to Truck 2 and O203 becomes a partner pickup, which carries NO vehicle. A
# null assigned_vehicle_id is the evidence of the pickup path, not a row to drop.
ORDER_ROWS = [
    _order_row("rev07", "O201", "TRUCK-01", status="DELIVERED"),
    _order_row("rev07", "O202", "TRUCK-01"),
    _order_row("rev07", "O203", "TRUCK-01"),
    _order_row("rev07", "O204", "TRUCK-02"),
    _order_row("rev07", "O205", "TRUCK-02"),
    _order_row("rev08", "O202", "TRUCK-02"),
    _order_row("rev08", "O203", None, status="PARTNER_PICKUP"),
    _order_row("rev08", "O204", "TRUCK-02"),
    _order_row("rev08", "O205", "TRUCK-02"),
]
INCIDENT_ROWS = [
    (TRUCK_INC, "VEHICLE_FAILURE", "SCOPING", "NONE", "{}", None, T(8, 20), T(8, 24)),
    (RECALL_INC, "FOOD_SAFETY_RECALL", "PARTIALLY_CONTAINED", "PARTIALLY_CONTAINED",
     '{"model_armor_correlation_id": "%s", "agent_fleet": %s}'
     % (CORRELATION, _json.dumps(FLEET)),
     "LTC-4471", T(9, 36), None),
]
# Truck 2 carries its existing 36 cases plus O202's 22. The 58/60 figure is the
# canonical arithmetic, not an asserted constant.
TRUCK2_LOAD = (CANONICAL_CAPACITY["truck_2_existing_cases"]
               + CANONICAL_CAPACITY["order_202_cases"])
VEHICLE_ROWS = [
    ("TRUCK-02", "Refrigerated Truck 2", CANONICAL_CAPACITY["capacity_limit"],
     TRUCK2_LOAD, True),
]
WORK_ROWS = [("WORK-SITE01", RECALL_INC, "OPEN", T(10, 5), None)]
BARRIER_ROWS = [("BARRIER-4471", "LTC-4471", "ACTIVE", T(10, 5), None)]

# Recovery replaces 40 safe cases: 18 to Agency 01 and 22 to Agency 02. Agency
# 03 keeps its truthful 20-case shortfall.
SHORTFALL_ROWS = [(
    "SF-A03", RECALL_INC, "OPEN", T(10, 10), "AGENCY-03",
    LETTUCE_RECALL["service_impact"]["shortfall_cases"],
)]
ALLOC_ROWS = [
    ("ALLOC-1", RECALL_INC, "COMMITTED", T(10, 10), "AGENCY-01", "LTC-5090", 18),
    ("ALLOC-2", RECALL_INC, "COMMITTED", T(10, 10), "AGENCY-02", "LTC-5090", 22),
]
CONSTRAINT_ROWS = [(PLAN, "LOT_EXCLUSION", "LTC-4471 excluded", T(10, 5))]

# The repair proposal the fleet produced at 08:21, after the 08:20 fault and
# before the 08:24 approval. Its diff is read from the SAME canonical approval
# seed the KMS envelope binds, so the proposal an operator sees and the diff
# that gets signed cannot drift apart.
REPAIR_PROPOSAL_ROW = (
    PLAN, "REPAIR_PROPOSAL", _json.dumps({
        "proposal_id": "PROP-FIXTURE-REV08",
        "source_event_id": "fixture-telematics-evt-1",
        "proposed_revision": CANONICAL_APPROVAL["proposed_revision"],
        "failed_vehicle_id": TRUCK_BREAKDOWN["incident"]["failed_vehicle_id"],
        "absorbing_vehicle_capacity_cases": CANONICAL_CAPACITY["capacity_limit"],
        "absorbing_vehicle_committed_cases":
            CANONICAL_CAPACITY["truck_2_existing_cases"],
        "absorbing_vehicle_projected_cases": (
            CANONICAL_CAPACITY["truck_2_existing_cases"]
            + CANONICAL_APPROVAL["reroute_cases"]),
        "plan_diff": {
            "reroute_order_id": CANONICAL_APPROVAL["reroute_order_id"],
            "reroute_cases": CANONICAL_APPROVAL["reroute_cases"],
            "reroute_target_vehicle": CANONICAL_APPROVAL["reroute_target_vehicle"],
            "pickup_order_id": CANONICAL_APPROVAL["pickup_order_id"],
            "pickup_cases": CANONICAL_APPROVAL["pickup_cases"],
        },
        "plan_diff_hash": "fixture-diffhash-rev08",
        "authority": "AGENT_PROPOSAL",
        "activation_supported": False,
    }, sort_keys=True), T(8, 21),
)

# The canonical six-node custody topology. Site 01 sits downstream of Agency 01,
# which is why Agency 01's current position is 10 and not its historical
# 18-case receipt.
CANONICAL_CUSTODY_NODES = LETTUCE_RECALL["custody_nodes"]
CUSTODY_PARENT = {
    "N-WH": None, "N-TR2": "N-WH", "N-STG": "N-WH",
    "N-AG01": "N-WH", "N-ST01": "N-AG01", "N-RESC": "N-WH",
}
CUSTODY_DEPTH = {"N-WH": 0, "N-TR2": 1, "N-STG": 1, "N-AG01": 1,
                 "N-ST01": 2, "N-RESC": 1}
# Only Site 01 is unconfirmed; every other position is acknowledged.
CUSTODY_UNCONFIRMED = {"N-ST01"}
# Edge case counts are the transfers themselves: Agency 01 received 18 and
# passed 8 downstream, leaving the 10 it currently holds.
CUSTODY_EDGE_CASES = {"N-TR2": 22, "N-STG": 20, "N-AG01": 18,
                      "N-ST01": 8, "N-RESC": 12}

CUSTODY_POSITIONS = [
    {"node_id": n["node_id"], "node_type": n["type"], "name": n["name"],
     "on_hand_cases": n["on_hand_cases"],
     "acknowledgment_status": ("UNCONFIRMED" if n["node_id"] in CUSTODY_UNCONFIRMED
                               else "CONFIRMED"),
     "path_depth": CUSTODY_DEPTH[n["node_id"]]}
    for n in CANONICAL_CUSTODY_NODES
]
CUSTODY_EDGES = [
    {"edge_id": f"E-{node_id}", "source_node_id": CUSTODY_PARENT[node_id],
     "target_node_id": node_id, "lot_id": "LTC-4471",
     "case_count": CUSTODY_EDGE_CASES[node_id],
     "is_sub_distribution": CUSTODY_PARENT[node_id] != "N-WH"}
    for node_id in CUSTODY_EDGE_CASES
]
CUSTODY_GRAPH = {
    "tenant_id": TENANT,
    "lot_id": "LTC-4471",
    "query_engine": "SPANNER_GRAPH_GQL",
    "paths": [{"root_node_id": "N-WH", "destination_node_id": n["node_id"],
               "path_depth": n["path_depth"]}
              for n in CUSTODY_POSITIONS if n["node_id"] != "N-WH"],
    "edges": CUSTODY_EDGES,
    "current_positions": CUSTODY_POSITIONS,
    "unique_current_cases": sum(n["on_hand_cases"] for n in CUSTODY_POSITIONS),
    "confirmed_cases": sum(n["on_hand_cases"] for n in CUSTODY_POSITIONS
                           if n["acknowledgment_status"] == "CONFIRMED"),
    "unconfirmed_cases": sum(n["on_hand_cases"] for n in CUSTODY_POSITIONS
                             if n["acknowledgment_status"] == "UNCONFIRMED"),
    "unconfirmed_positions": [n for n in CUSTODY_POSITIONS
                              if n["acknowledgment_status"] == "UNCONFIRMED"],
    "max_path_depth": 2,
    "node_count": len(CUSTODY_POSITIONS),
    "intermediate_subtotals_readded": False,
    "classification": "OBSERVED_LIVE",
}


def _partner_evidence_row(*, source_event_id, source_text, occurred_at,
                          committed_at, decision, reasons, proposal,
                          domain_mutations):
    before_after = {
        "custody": {"node_id": "N-ST01", "name": "Site 01", "cases": 8,
                    "before": "UNCONFIRMED",
                    "after": "CONFIRMED" if decision == "APPLIED" else "UNCONFIRMED"},
        "work_item": {"work_item_id": "WORK-PCF-FIXTURE", "before": "OPEN",
                      "after": "COMPLETED" if decision == "APPLIED" else "OPEN"},
    }
    claims = {
        name: {"state": "PRESENT" if not reasons else "MISSING",
               "reason": "LITERAL_SOURCE_ANCHOR" if not reasons else "CLAIM_NOT_PRESENT"}
        for name in ("lot", "quantity", "location", "disposition")
    }
    claims["confirmation_time"] = {
        "state": "PRESENT" if decision == "APPLIED" else "MISSING",
        "reason": "LITERAL_SOURCE_ANCHOR" if decision == "APPLIED" else "OPTIONAL_CLAIM_NOT_PRESENT",
    }
    return (
        source_event_id, "PARTNER_CUSTODY_EVIDENCE_RECEIVED", RECALL_INC,
        "PARTNER-AGENCY-01", occurred_at, committed_at, source_text,
        "fixture-partner-subject", "partner-callback@example.com",
        "https://orchestrator.example.run.app/partner-evidence",
        "https://accounts.google.com", "AUTHENTICATED_PARTNER_CALLBACK",
        _json.dumps({"status": "APPROVED", "managed_operation": "sanitizeUserPrompt",
                     "safety_verdict": "PASSED", "correlation_id": "fixture-trace"}),
        _json.dumps(proposal), decision, _json.dumps(reasons),
        _json.dumps({"claims": claims, "before_after": before_after,
                     "qualifying_disposition": "ISOLATED_IN_QUARANTINE"}),
        _json.dumps({"type": "CONFIRM_CUSTODY"}),
        "full-shelf.partner-operations.v1", "gemini-3.5-flash",
        "google-adk/2.6.1", f"fixture-session-{source_event_id}",
        f"fixture-invocation-{source_event_id}", f"fixture-event-{source_event_id}",
        f"fixture-RCT-{source_event_id}", domain_mutations, 1, committed_at,
    )


VAGUE_PROPOSAL = {
    "incident_id": RECALL_INC, "partner_id": "PARTNER-AGENCY-01",
    "site_id": "SITE-01", "custody_node_id": "N-ST01",
    "work_item_id": "WORK-PCF-FIXTURE",
    "expected_acknowledgment_status": "UNCONFIRMED",
    "requested_acknowledgment_status": "CONFIRMED",
    "lot": None, "quantity": None, "location": None, "disposition": None,
    "confirmation_time": None, "requested_mutation": "CONFIRM_CUSTODY",
    "rationale": "The response intends completion but omits required custody facts.",
    "confidence": 0.72,
}
COMPLETE_PROPOSAL = {
    **VAGUE_PROPOSAL,
    "lot": {"value": "LTC-4471", "quote": "LTC-4471"},
    "quantity": {"value": 8, "quote": "8 cases"},
    "location": {"value": "Site 01", "quote": "Site 01"},
    "disposition": {"value": "ISOLATED_IN_QUARANTINE",
                    "quote": "ISOLATED_IN_QUARANTINE"},
    "confirmation_time": {"value": "10:18", "quote": "confirmed at 10:18"},
    "rationale": "Every required custody fact has a literal source anchor.",
    "confidence": 0.99,
}
VAGUE_EVIDENCE_ROW = _partner_evidence_row(
    source_event_id="fixture-partner-vague",
    source_text="We pulled the remaining lettuce. Should be all good.",
    occurred_at=T(10, 15), committed_at=T(10, 15), decision="DENIED",
    reasons=["MISSING_LOT_EVIDENCE", "MISSING_QUANTITY_EVIDENCE",
             "MISSING_LOCATION_EVIDENCE", "MISSING_DISPOSITION_EVIDENCE"],
    proposal=VAGUE_PROPOSAL, domain_mutations=0,
)
# The canonical Friday reply, committed at 10:11 — BEFORE the closure
# decision at 10:12. It is why the eight cases stay unconfirmed, so it is
# canonical history rather than an isolated proof: the refusal at event 21
# cannot be explained without it. Identical in substance to the vague proof
# row; only the source event and its time differ.
CANONICAL_PARTNER_REPLY_ROW = _partner_evidence_row(
    source_event_id="fixture-partner-canonical-vague",
    source_text="We pulled the remaining lettuce. Should be all good.",
    occurred_at=T(10, 11), committed_at=T(10, 11), decision="DENIED",
    reasons=["MISSING_LOT_EVIDENCE", "MISSING_QUANTITY_EVIDENCE",
             "MISSING_LOCATION_EVIDENCE", "MISSING_DISPOSITION_EVIDENCE"],
    proposal=VAGUE_PROPOSAL, domain_mutations=0,
)
COMPLETE_EVIDENCE_ROW = _partner_evidence_row(
    source_event_id="fixture-partner-complete",
    source_text=("LTC-4471 · 8 cases · ISOLATED_IN_QUARANTINE at Site 01 · "
                 "confirmed at 10:18."),
    occurred_at=T(10, 18), committed_at=T(10, 18), decision="APPLIED",
    reasons=[], proposal=COMPLETE_PROPOSAL, domain_mutations=2,
)


def _database(*, include_next_day=False, vehicles=VEHICLE_ROWS,
              work_rows=WORK_ROWS, incident_rows=INCIDENT_ROWS,
              receipts=ALL_RECEIPTS, approval_rows=APPROVAL_ROWS,
              alloc_rows=ALLOC_ROWS, shortfall_rows=SHORTFALL_ROWS,
              constraint_rows=tuple(CONSTRAINT_ROWS) + (CANDIDATE_UNASSIGNED_ROW,
                                                        REPAIR_PROPOSAL_ROW),
              partner_evidence_rows=()):
    """Fake Spanner that ENFORCES every predicate the handler actually binds.

    A fake that ignores a WHERE clause cannot prove scoping: the adversarial
    rows would be filtered by Python in the handler, or not filtered at all,
    and the test would pass either way. So each branch below applies the same
    predicates the production SQL declares, and any row the query does not ask
    for is never returned.
    """
    db = MagicMock()
    snap = MagicMock()

    def execute_sql(sql, params=None, param_types=None):
        params = params or {}
        as_of = params.get("as_of")
        pid = params.get("plan_id")
        incident_ids = params.get("incident_ids")

        def scoped(rows, ts_index, *, plan_index=None, incident_index=None):
            out = []
            for row in rows:
                if as_of is not None and row[ts_index] > as_of:
                    continue
                if plan_index is not None and pid is not None and row[plan_index] != pid:
                    continue
                if (incident_index is not None and incident_ids is not None
                        and row[incident_index] not in incident_ids):
                    continue
                out.append(row)
            return out

        if "FROM Receipts" in sql:
            return list(receipts)
        if "FROM PlanRevisions" in sql:
            rows = NEXT_DAY_ROWS if pid == NEXT_PLAN else PLAN_ROWS
            return scoped(rows, 3, plan_index=0)
        if "FROM Orders" in sql:
            # Production scopes every Orders read by plan_id. The fake must
            # too, or a Saturday candidate row could leak into Friday here and
            # the isolation tests would be proving nothing.
            rows = CANDIDATE_ORDER_ROWS if pid == NEXT_PLAN else ORDER_ROWS
            revision = params.get("revision")
            if revision is not None:
                rows = [r for r in rows if r[0] == revision]
            if "status='CANDIDATE'" in sql.replace(" ", ""):
                # (order_id, agency_id, agency_name, cases, lot, vehicle)
                return [(r[1], r[7], r[2], r[3], r[4], r[5])
                        for r in rows if r[6] == "CANDIDATE"]
            return [tuple(r[:7]) for r in rows]
        if "FROM Approvals" in sql:
            rows = scoped(approval_rows, 6, plan_index=1)
            # The handler also binds the intended revision transition.
            src = params.get("source_revision")
            proposed = params.get("proposed_revision")
            if src is not None:
                rows = [r for r in rows if r[2] == src and r[3] == proposed]
            return rows
        if "FROM Incidents" in sql:
            return scoped(incident_rows, 6)
        if "FROM MovementBarriers" in sql:
            return scoped(BARRIER_ROWS, 3)
        if "FROM RecoveryAllocations" in sql:
            return scoped(alloc_rows, 3, incident_index=1)
        if "FROM RecoveryShortfalls" in sql:
            return scoped(shortfall_rows, 3, incident_index=1)
        if "FROM WorkItems" in sql:
            return scoped(work_rows, 3, incident_index=1)
        if "FROM PartnerEvidenceEvents" in sql:
            return scoped(partner_evidence_rows, 27)
        if "FROM PlanConstraints" in sql:
            rows = scoped(constraint_rows, 3, plan_index=0)
            if "subject_id" in sql:
                # Draft read projects (constraint_type, subject_id, details).
                # Seed rows carry the details JSON in an optional 5th slot.
                return [(r[1], r[2], r[4] if len(r) > 4 else "{}")
                        for r in rows]
            return rows
        if "FROM Vehicles" in sql:
            return list(vehicles)
        return []

    snap.execute_sql.side_effect = execute_sql
    db.snapshot.return_value.__enter__.return_value = snap
    return db


def project(as_of, *, include_next_day=False, db=None, custody_graph=CUSTODY_GRAPH):
    client = TestClient(orchestrator_main.app)
    identity = MagicMock(subject="operator-subject", email="op@example.com")
    scope = MagicMock(tenant_id=TENANT, database_id="full-shelf-audit-test")
    url = "/api/v1/projections/demo-beats"
    if as_of is not None:
        raw = as_of if isinstance(as_of, str) else as_of.isoformat()
        url += f"?as_of={quote(raw)}"
    if include_next_day:
        url += ("&" if "?" in url else "?") + "include_next_day_draft=true"
    # Override the FastAPI dependency by key. Patching the module attribute is
    # not enough: the route already captured the original callable at import.
    orchestrator_main.app.dependency_overrides[
        orchestrator_main.require_frontend_authority
    ] = lambda: (identity, scope, DAY)
    with (
        patch.object(orchestrator_main, "get_spanner_database",
                     return_value=db if db is not None else _database()),
        patch.object(orchestrator_main, "_run_managed_custody_graph",
                     return_value=custody_graph),
    ):
        try:
            return client.get(url)
        finally:
            orchestrator_main.app.dependency_overrides.clear()


def blob(payload):
    import json as _j
    return _j.dumps(payload)


# --- 1. cross-day exclusion -------------------------------------------------
def test_1_saturday_draft_excluded_from_every_field_of_friday_response():
    body = project(T(23, 59)).json()
    assert "next_day_draft" not in body
    assert "rev01" not in blob(body)
    assert NEXT_PLAN not in blob(body)


# --- 2. 08:05 excludes all later Friday state -------------------------------
def test_2_0805_excludes_later_revisions_and_incidents():
    body = project(T(8, 5)).json()
    revs = [r["revision"] for r in body["current_day"]["plan_revisions"]]
    assert revs == ["rev07"]
    assert body["current_day"]["incidents"] == []
    assert "LTC-4471" not in blob(body["current_day"]["incidents"])


# --- 3. 08:24 includes rev08, excludes recall -------------------------------
def test_3_0824_includes_rev08_excludes_recall():
    body = project(T(8, 24)).json()
    revs = [r["revision"] for r in body["current_day"]["plan_revisions"]]
    assert "rev08" in revs
    ids = [i["incident_id"] for i in body["current_day"]["incidents"]]
    assert TRUCK_INC in ids and RECALL_INC not in ids
    assert body["execution_evidence_as_of"]["custody_graph"] is None


# --- 4. 09:35 excludes completed custody/recovery/refusal -------------------
def test_4_0935_excludes_completed_custody_recovery_refusal():
    body = project(T(9, 35)).json()
    assert body["execution_evidence_as_of"]["custody_graph"] is None
    assert body["current_day"]["recovery"]["allocations"] == []
    assert body["agent_activity_as_of"] is None
    for inc in body["current_day"]["incidents"]:
        assert inc["refusal"] is None


# --- 5. custody 96/88/8 appears only once no later mutator remains ----------
def test_5_custody_omitted_while_a_later_mutation_is_still_outstanding():
    """At 10:05 the barrier has committed, but ALLOCATE_SAFE_STOCK at 10:10
    also mutates custody. CustodyNodes keeps no history, so the present row is
    a later value and Amendment 1 requires omission rather than a leak."""
    body = project(T(10, 5)).json()
    assert body["execution_evidence_as_of"]["custody_graph"] is None
    omitted = {o["field"]: o["reason"] for o in
               body["projection_boundary"]["omitted_fields"]}
    assert omitted["custody_graph"] == "PRE_BOUNDARY_STATE_NOT_RETAINED"
    assert body["current_day"]["recovery"]["allocations"] == []
    assert body["agent_activity_as_of"] is None
    recall = [i for i in body["current_day"]["incidents"]
              if i["incident_id"] == RECALL_INC][0]
    assert recall["refusal"] is None


def test_5b_custody_96_88_8_visible_once_all_mutations_are_committed():
    """After every custody mutator has committed, the present row IS the
    boundary row, so the full 96/88/8 reconciliation is truthfully readable."""
    body = project(T(23, 59)).json()
    custody = body["execution_evidence_as_of"]["custody_graph"]
    assert custody["unique_current_cases"] == 96
    assert custody["confirmed_cases"] == 88
    assert custody["unconfirmed_cases"] == 8


# --- 6. explicit Tomorrow returns Saturday rev01 exactly once ---------------
def test_6_explicit_tomorrow_returns_rev01_exactly_once():
    body = project(T(23, 59), include_next_day=True).json()
    assert body["next_day_draft"]["revision"] == "rev01"
    assert body["next_day_draft"]["approval_required"] is True
    # Tomorrow is confined to next_day_draft. Asserting containment directly
    # is stronger than counting occurrences, which a candidate order id
    # legitimately embedding the plan name would otherwise trip.
    assert body["next_day_draft"]["plan_id"] == NEXT_PLAN
    for key, value in body.items():
        if key != "next_day_draft":
            assert NEXT_PLAN not in blob(value), key


# --- 7. carry-forward without unrelated history ----------------------------
def test_7_carry_forward_obligations_without_unrelated_history():
    body = project(T(23, 59)).json()
    kinds = {o["kind"] for o in body["carry_forward_obligations"]}
    assert {"ACKNOWLEDGMENT_OBLIGATION", "MOVEMENT_BARRIER",
            "RECOVERY_SHORTFALL", "UNRESOLVED_INCIDENT"} <= kinds
    refs = {o["reference_id"] for o in body["carry_forward_obligations"]}
    assert TRUCK_INC not in refs  # resolved at 08:24, must not carry forward


# --- 8. tenant isolation ---------------------------------------------------
def test_8_tenant_isolation_scopes_every_query():
    db = _database()
    project(T(23, 59), db=db)
    snap = db.snapshot.return_value.__enter__.return_value
    for call in snap.execute_sql.call_args_list:
        params = call.kwargs.get("params") or {}
        assert params.get("tenant") == TENANT


# --- 10. deterministic replay ----------------------------------------------
def test_10_fixed_as_of_replay_is_deterministic():
    a = project(T(10, 13)).json()
    b = project(T(10, 13)).json()
    assert a == b


# --- 11. as_of outside operating day rejected ------------------------------
def test_11_as_of_outside_operating_day_is_rejected():
    resp = project(datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "AS_OF_OUTSIDE_AUTHORITY_OPERATING_DAY"


# --- 12 / Amendment 1: later mutation omits timeless row --------------------
def test_12_amendment1_later_vehicle_mutation_omits_current_row():
    """Vehicles hold only the present value. A rev08 SAVE_PLAN_REVISION after
    the boundary proves the current 58/60 row is a later value, so it must be
    omitted rather than leaked backwards as though it were the 08:05 truth."""
    body = project(T(8, 5)).json()
    assert body["current_day"]["vehicles"] is None
    omitted = {o["field"]: o["reason"] for o in
               body["projection_boundary"]["omitted_fields"]}
    assert omitted["current_day.vehicles"] == "PRE_BOUNDARY_STATE_NOT_RETAINED"


def test_12b_amendment1_after_all_mutations_timeless_row_is_safe():
    body = project(T(23, 59)).json()
    assert body["current_day"]["vehicles"][0]["assigned_cases"] == 58


# --- 13 / next_day_draft key absent by default -----------------------------
def test_13_next_day_draft_key_absent_by_default():
    body = project(T(23, 59)).json()
    assert "next_day_draft" not in body


# --- Amendment 2: same action_type, different targets ----------------------
def test_amendment2_same_action_type_different_targets_do_not_unlock():
    """Both incidents commit SET_INCIDENT_STATUS. The truck incident's SCOPING
    receipt must never unlock the recall incident's lifecycle."""
    body = project(T(8, 21)).json()
    ids = [i["incident_id"] for i in body["current_day"]["incidents"]]
    assert ids == [TRUCK_INC]
    truck = body["current_day"]["incidents"][0]
    # A vehicle failure runs ACTIVE -> RESOLVED, not the recall containment
    # ladder. Its own SCOPING receipt opens it; it must not read as a recall
    # stage, and it must not unlock the recall incident's lifecycle either.
    assert truck["status"] == "ACTIVE"
    assert truck["terminal_state"] == "NONE"


def test_replacement_lot_maps_to_a_configured_source_facility(monkeypatch):
    """The lot is authoritative; the facility is tenant configuration."""
    monkeypatch.setenv("LOT_SOURCE_FACILITIES", "LTC-5090=Central Warehouse")
    recovery = project(T(10, 10)).json()["current_day"]["recovery"]
    assert recovery["allocations"], "canonical day allocates replacement stock"
    for allocation in recovery["allocations"]:
        assert allocation["lot_id"] == "LTC-5090"
        assert allocation["source_facility"] == "Central Warehouse"
        assert allocation["source_facility_basis"] == "CONFIGURED_TENANT_REFERENCE"


def test_unconfigured_replacement_lot_projects_no_facility(monkeypatch):
    """An unconfigured tenant gets null, never a placeholder.

    A placeholder would render as a located fact on the operator surface.
    """
    monkeypatch.setenv("LOT_SOURCE_FACILITIES", "")
    recovery = project(T(10, 10)).json()["current_day"]["recovery"]
    for allocation in recovery["allocations"]:
        assert allocation["source_facility"] is None
        # The basis still states what the field would have meant.
        assert allocation["source_facility_basis"] == "CONFIGURED_TENANT_REFERENCE"


def test_source_facility_configuration_never_invents_custody(monkeypatch):
    """Configuring a facility must not add a custody node or edge.

    Replacement custody is unsupported: no hand-off of a replacement case is
    recorded, so the custody graph must stay at its canonical 96 unique cases.
    """
    monkeypatch.setenv("LOT_SOURCE_FACILITIES", "LTC-5090=Central Warehouse")
    body = project(T(10, 10)).json()
    custody = body["execution_evidence_as_of"]["custody_graph"]
    # The custody graph tracks the recalled lot only, at its canonical totals.
    assert custody["lot_id"] == "LTC-4471"
    assert (custody["unique_current_cases"], custody["confirmed_cases"],
            custody["unconfirmed_cases"]) == (96, 88, 8)
    # The replacement lot appears nowhere in the custody evidence.
    assert "LTC-5090" not in _json.dumps(custody)


def test_stop_sequence_matches_the_canonical_ordered_manifest():
    """Sequence is the committed manifest order, read from the seed.

    The morning-plan seed carries an ordered assigned_orders manifest per
    vehicle. The projected sequence must reproduce it rather than invent an
    order, so the numbered stops an operator sees are source-backed.
    """
    expected = {
        truck["vehicle_id"]: list(truck["assigned_orders"])
        for truck in MORNING_PLAN["trucks"]
    }
    dispatch = project(T(8, 5)).json()["current_day"]["dispatch"]
    for vehicle in dispatch["vehicles"]:
        ordered = [s["order_id"] for s in sorted(vehicle["stops"],
                                                 key=lambda s: s["sequence"])]
        assert ordered == expected[vehicle["vehicle_id"]]
        # 1-based and contiguous, so a client can render 1..n with no gaps.
        assert [s["sequence"] for s in
                sorted(vehicle["stops"], key=lambda s: s["sequence"])] == \
            list(range(1, len(ordered) + 1))


def test_stop_sequence_is_declared_as_manifest_order_not_a_route():
    """The sequence must never be presentable as an optimized route."""
    dispatch = project(T(8, 5)).json()["current_day"]["dispatch"]
    assert dispatch["sequence_basis"] == "COMMITTED_MANIFEST_ORDER"


def test_partner_pickup_carries_no_vehicle_stop_sequence():
    """O203 leaves the truck manifest, so it holds no position on one."""
    dispatch = project(T(23, 59)).json()["current_day"]["dispatch"]
    pickups = dispatch["partner_pickups"]
    assert [p["order_id"] for p in pickups] == ["O203"]
    assert pickups[0]["sequence"] is None
    routed = {s["order_id"] for v in dispatch["vehicles"] for s in v["stops"]}
    assert "O203" not in routed


def test_repaired_revision_resequences_the_absorbing_vehicle():
    """Truck 2 absorbs O202, so its manifest renumbers contiguously."""
    dispatch = project(T(23, 59)).json()["current_day"]["dispatch"]
    truck2 = next(v for v in dispatch["vehicles"] if v["vehicle_id"] == "TRUCK-02")
    ordered = sorted(truck2["stops"], key=lambda s: s["sequence"])
    assert [s["order_id"] for s in ordered] == ["O202", "O204", "O205"]
    assert [s["sequence"] for s in ordered] == [1, 2, 3]


def test_vehicle_failure_is_active_then_resolved_by_its_repair_revision():
    """The truck breakdown is a real projected incident with its own lifecycle.

    It is absent before it happens, ACTIVE once its own status receipt commits,
    and RESOLVED only when the approved repair revision commits. The operator
    surface derives its incident badge from this, never from view state.
    """
    assert project(T(8, 19)).json()["current_day"]["incidents"] == []

    def truck_at(as_of):
        incidents = project(as_of).json()["current_day"]["incidents"]
        return next(i for i in incidents if i["incident_id"] == TRUCK_INC)

    assert truck_at(T(8, 20))["status"] == "ACTIVE"
    assert truck_at(T(8, 23))["status"] == "ACTIVE"
    # rev08 is the approved repair; its commit resolves the failure.
    assert truck_at(T(8, 24))["status"] == "RESOLVED"
    assert truck_at(T(23, 59))["status"] == "RESOLVED"
    # Resolved is not terminal containment, and it never carries forward.
    assert truck_at(T(23, 59))["terminal_state"] == "NONE"


def test_vehicle_failure_is_not_resolved_by_the_pre_incident_morning_plan():
    """rev07 committed at 07:30, before the 08:20 failure.

    An earlier plan receipt must never read as the repair of a failure that had
    not happened yet, so the incident stays ACTIVE until rev08 commits.
    """
    incidents = project(T(8, 21)).json()["current_day"]["incidents"]
    truck = next(i for i in incidents if i["incident_id"] == TRUCK_INC)
    assert truck["status"] == "ACTIVE"


def test_recall_incident_never_uses_the_vehicle_failure_lifecycle():
    """rev08's plan receipt must not resolve the recall incident."""
    incidents = project(T(23, 59)).json()["current_day"]["incidents"]
    recall = next(i for i in incidents if i["incident_id"] == RECALL_INC)
    assert recall["status"] == "PARTIALLY_CONTAINED"
    assert recall["terminal_state"] == "PARTIALLY_CONTAINED"


def test_amendment2_terminal_state_requires_its_own_recomputed_receipt():
    """At 10:06 CONTAINMENT_IN_PROGRESS has committed but PARTIALLY_CONTAINED
    has not. Position in the receipt list must not promote it."""
    body = project(T(10, 6)).json()
    recall = [i for i in body["current_day"]["incidents"]
              if i["incident_id"] == RECALL_INC][0]
    assert recall["status"] == "CONTAINMENT_IN_PROGRESS"
    assert recall["terminal_state"] == "NONE"


# --- Amendment 3: open-as-of, not present-day-open -------------------------
def test_amendment3_later_resolved_obligation_appears_open_before_resolution():
    resolved_later = [("WORK-SITE01", RECALL_INC, "COMPLETED", T(10, 5), T(20, 0))]
    db = _database(work_rows=resolved_later)
    early = project(T(11, 0), db=db).json()
    kinds = [o["kind"] for o in early["carry_forward_obligations"]]
    assert "ACKNOWLEDGMENT_OBLIGATION" in kinds

    db2 = _database(work_rows=resolved_later)
    late = project(T(21, 0), db=db2).json()
    kinds_late = [o["kind"] for o in late["carry_forward_obligations"]]
    assert "ACKNOWLEDGMENT_OBLIGATION" not in kinds_late


# --- Amendment 4: Healthy has no capacity claim ---------------------------
def test_amendment4_healthy_carries_no_capacity_claim():
    body = project(T(8, 5)).json()
    assert body["current_day"]["vehicles"] is None
    assert "24 spare" not in blob(body)
    commitments = body["current_day"]["commitments"]
    assert {c["order_id"] for c in commitments} == {
        "O201", "O202", "O203", "O204", "O205"}


def test_amendment4_truck_failure_capacity_proof_from_immutable_orders():
    """36 is derivable from immutable rev07 Orders on Truck 2 (15 + 21)."""
    body = project(T(8, 24)).json()
    rev07_truck2 = [c for c in body["current_day"]["commitments"]
                    if c["revision"] == "rev07" and c["vehicle"] == "TRUCK-02"]
    assert sum(c["cases"] for c in rev07_truck2) == 36
    rev08 = [c for c in body["current_day"]["commitments"]
             if c["revision"] == "rev08" and c["order_id"] == "O202"]
    assert rev08[0]["cases"] == 22


# --- Delta 3: refusal is backend-sourced -----------------------------------
def test_delta3_refusal_reports_denied_zero_mutations_from_ledger():
    body = project(T(10, 13)).json()
    recall = [i for i in body["current_day"]["incidents"]
              if i["incident_id"] == RECALL_INC][0]
    assert recall["refusal"]["decision"] == "DENIED"
    assert recall["refusal"]["mutations_applied"] == 0
    assert recall["terminal_state"] == "PARTIALLY_CONTAINED"


def test_delta3_fleet_evidence_durable_and_boundary_gated():
    body = project(T(10, 13)).json()
    fleet = body["agent_activity_as_of"]
    assert fleet["coordination_run_id"] == "fixture-run-coord-1"
    assert fleet["proposal_status"] == "PROPOSED"
    assert fleet["delegation_trace"][1]["specialist_run_id"] == "fixture-run-recall-1"


def test_sse_cursor_binds_receipt_without_projecting_material_fields():
    event_id = orchestrator_main._encode_receipt_cursor(T(10, 12), "fixture-RCT-1")
    timestamp, receipt_id = orchestrator_main._decode_receipt_cursor(event_id)
    assert timestamp == T(10, 12)
    assert receipt_id == "fixture-RCT-1"
    assert "DENIED" not in event_id
    assert CORRELATION not in event_id


# ---------------------------------------------------------------------------
# UI PROOF PROJECTION v2 — bounded authority-backed hero-loop surfaces.
#
# Every assertion below proves one of two things: that an authority-backed
# surface is projected once it exists, or that it is absent before it exists.
# Nothing here asserts a value the schema cannot source from a committed
# record, a persisted fleet result, or a transparent derivation.
# ---------------------------------------------------------------------------

import jsonschema as _jsonschema

REPO_ROOT = _pathlib.Path(__file__).resolve().parents[3]
UI_SCHEMA = _json.loads(
    (REPO_ROOT / "packages/contracts/schemas/ui_projection.json").read_text()
)
REPLAY_FIXTURES = REPO_ROOT / "tools/replay/fixtures"

_replay_spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location(
    "_fs_generate_fixtures", REPO_ROOT / "tools/replay/generate_fixtures.py"
)
_replay_gen = __import__("importlib.util", fromlist=["util"]).module_from_spec(_replay_spec)
_replay_spec.loader.exec_module(_replay_gen)
_reclassify = _replay_gen._reclassify

# The 12 canonical beats and the boundary that produces each one.
CANONICAL_BEATS = [
    ("healthy", T(8, 5), False),
    ("truckfail", T(8, 20), False),
    ("review", T(8, 21), False),
    ("geo", T(8, 22), False),
    ("rev08", T(8, 24), False),
    ("recall_received", T(9, 36), False),
    ("processing", T(10, 4), False),
    ("custody", T(10, 5), False),
    ("recovery", T(10, 10), False),
    ("refusal", T(10, 13), False),
    ("outcome", T(16, 30), False),
    ("tomorrow", T(17, 0), True),
]


def _beat(name):
    as_of, next_day = next((b[1], b[2]) for b in CANONICAL_BEATS if b[0] == name)
    return project(as_of, include_next_day=next_day).json()


# --- contract parity -------------------------------------------------------
@pytest.mark.parametrize("name,as_of,next_day", CANONICAL_BEATS)
def test_v2_handler_matches_schema_at_every_canonical_boundary(name, as_of, next_day):
    _jsonschema.validate(project(as_of, include_next_day=next_day).json(), UI_SCHEMA)


@pytest.mark.parametrize("name,as_of,next_day", CANONICAL_BEATS)
def test_v2_handler_matches_committed_replay_fixture(name, as_of, next_day):
    """The fixture must be what this handler emits, not a hand-edited artifact.

    Reclassification is applied through the generator's own function, so this
    proves fixture parity rather than re-implementing the generation rule.

    The committed fixtures are HISTORICAL EVIDENCE and are never regenerated to
    match a changed handler. They were produced with the canonical partner
    reply present — it lands at 10:11 and is what the closure refusal is
    explained by — so parity has to feed the handler the same input. Boundaries
    at or after 10:11 therefore supply that row; earlier ones must not, because
    the evidence had not arrived yet.
    """
    reply_has_landed = as_of is not None and as_of >= T(10, 11)
    database = _database(
        partner_evidence_rows=(CANONICAL_PARTNER_REPLY_ROW,)
        if reply_has_landed else (),
        # Its DENIED receipt is part of the same historical record: the reply
        # was processed and refused, applying zero domain mutations and one
        # evidence mutation.
        receipts=(
            ALL_RECEIPTS + [partner_receipt(
                "fixture-partner-canonical-vague", T(10, 11), "DENIED", 0)]
            if reply_has_landed else ALL_RECEIPTS
        ),
    )
    live = _reclassify(
        project(as_of, include_next_day=next_day, db=database).json()
    )
    stored = _json.loads((REPLAY_FIXTURES / f"{name}.json").read_text())
    stored.pop("replay_notice", None)
    assert live == stored


# --- approval and rev07->rev08 diff ---------------------------------------
def test_v2_approval_absent_before_it_is_verified():
    for name in ("healthy", "truckfail", "review", "geo"):
        assert _beat(name)["current_day"]["approvals"] == [], name


def test_v2_approval_is_revision_bound_with_diff_and_key_version():
    approval = _beat("rev08")["current_day"]["approvals"][0]
    assert (approval["source_revision"], approval["proposed_revision"]) == (
        "rev07", "rev08")
    assert approval["state"] == "VERIFIED"
    assert approval["kms_key_version"].startswith("projects/")
    assert approval["approver_identity_class"] == "VERIFIED_HUMAN_OPERATOR"
    changes = {row["change_type"]: row for row in approval["plan_diff"]}
    assert changes["REROUTE"]["order_id"] == "O202"
    assert changes["REROUTE"]["cases"] == 22
    assert changes["PICKUP"]["order_id"] == "O203"
    assert changes["PICKUP"]["cases"] == 20


def test_v2_kms_signature_never_projected_at_any_boundary():
    for name, _, _ in CANONICAL_BEATS:
        assert "kms_signature" not in blob(_beat(name)), name


def test_v2_approver_email_is_never_projected_verbatim():
    """Identity class and domain are safe; the operator's address is not."""
    for name, _, _ in CANONICAL_BEATS:
        assert "operator@example.com" not in blob(_beat(name)), name


# --- five-agent activity ---------------------------------------------------
def test_v2_five_agent_evidence_absent_before_the_fleet_gate_commits():
    for name in ("healthy", "recall_received", "processing", "custody"):
        assert _beat(name)["agent_activity_as_of"] is None, name


def test_v2_all_five_accepted_agents_are_projected_from_persisted_evidence():
    fleet = _beat("refusal")["agent_activity_as_of"]
    assert [a["display_name"] for a in fleet["agents"]] == [
        "Incident Lead", "Recall Intake & Extraction", "Network & Custody",
        "Fulfillment Planning & Recovery", "Partner Operations",
    ]
    assert all(a["state"] == "COMPLETED" for a in fleet["agents"])
    # Each specialist reports its OWN run/session, never the coordinator's.
    specialists = [a for a in fleet["agents"] if a["role"] == "GOVERNED_SPECIALIST"]
    assert len({a["session_id"] for a in specialists}) == 5
    assert all(a["session_id"] != fleet["coordinator_session_id"] for a in specialists)
    assert fleet["topology"] == "SEPARATELY_CORRELATED_SPECIALIST_RUNNERS"


def test_v2_agent_rail_never_invents_running_waiting_or_durations():
    body = _beat("refusal")
    for agent in body["agent_activity_as_of"]["agents"]:
        assert agent["state"] in {"COMPLETED", "NOT_YET_REPORTED", "NOT_INVOLVED"}
        assert "duration" not in agent and "started_at" not in agent
    raw = blob(body["agent_activity_as_of"])
    assert "RUNNING" not in raw and "WAITING" not in raw


def test_v2_tool_invocations_claimed_only_where_persisted():
    """Only Network & Custody holds tools today; no other agent may claim any."""
    agents = {a["agent_id"]: a for a in _beat("refusal")["agent_activity_as_of"]["agents"]}
    assert agents["full-shelf.network-custody.v2"]["tool_invocations"]
    for agent_id, agent in agents.items():
        if agent_id != "full-shelf.network-custody.v2":
            assert agent["tool_invocations"] == [], agent_id


def test_v2_agent_missing_from_persisted_trace_is_not_yet_reported():
    """A partial fleet result must never be completed by inference."""
    partial = dict(FLEET, delegation_trace=FLEET["delegation_trace"][:2])
    rows = [
        INCIDENT_ROWS[0],
        (RECALL_INC, "FOOD_SAFETY_RECALL", "PARTIALLY_CONTAINED",
         "PARTIALLY_CONTAINED",
         _json.dumps({"model_armor_correlation_id": CORRELATION,
                      "agent_fleet": partial}),
         "LTC-4471", T(9, 36), None),
    ]
    body = project(T(10, 13), db=_database(incident_rows=rows)).json()
    states = {a["display_name"]: a["state"]
              for a in body["agent_activity_as_of"]["agents"]}
    assert states["Fulfillment Planning & Recovery"] == "NOT_YET_REPORTED"
    assert states["Partner Operations"] == "NOT_YET_REPORTED"
    assert states["Recall Intake & Extraction"] == "COMPLETED"


def test_v2_model_armor_is_not_a_member_of_the_agent_fleet():
    fleet = _beat("refusal")["agent_activity_as_of"]
    assert len(fleet["agents"]) == 5
    assert not any("armor" in a["agent_id"].lower() for a in fleet["agents"])
    # It remains projected as the screening boundary it actually is.
    recall = [i for i in _beat("refusal")["current_day"]["incidents"]
              if i["incident_id"] == RECALL_INC][0]
    assert recall["model_armor_screening"]["result"] == "PASS"


# --- custody graph ---------------------------------------------------------
def test_v2_custody_graph_absent_before_it_is_historically_safe():
    # Before the recall exists there is no custody graph to omit, so no
    # omission is recorded. Once the incident exists but its reconciliation has
    # not committed, the omission is stated explicitly.
    assert _beat("healthy")["execution_evidence_as_of"]["custody_graph"] is None
    assert not _beat("healthy")["projection_boundary"]["omitted_fields"] == [
        {"field": "custody_graph", "reason": "NOT_COMMITTED_AS_OF_BOUNDARY"}]
    for name in ("recall_received", "processing"):
        body = _beat(name)
        assert body["execution_evidence_as_of"]["custody_graph"] is None, name
        assert any(o["field"] == "custody_graph"
                   for o in body["projection_boundary"]["omitted_fields"]), name


def test_v2_custody_graph_preserves_canonical_reconciliation():
    graph = _beat("refusal")["execution_evidence_as_of"]["custody_graph"]
    assert graph["unique_current_cases"] == 96
    assert graph["confirmed_cases"] == 88
    assert graph["unconfirmed_cases"] == 8
    assert graph["node_count"] == 6
    assert len(graph["current_positions"]) == 6
    assert graph["paths"]


def test_v2_custody_graph_returns_no_geography():
    raw = blob(_beat("refusal")["execution_evidence_as_of"]["custody_graph"])
    for banned in ("latitude", "longitude", "coordinates", "bearing", "geometry"):
        assert banned not in raw, banned


# --- dispatch and capacity -------------------------------------------------
def test_v2_dispatch_exposes_authoritative_capacity_arithmetic():
    # The canonical 58/60 capacity proof is readable at the outcome boundary,
    # where no later mutation of the timeless Vehicles row exists.
    truck = [v for v in _beat("outcome")["current_day"]["dispatch"]["vehicles"]
             if v["vehicle_id"] == "TRUCK-02"][0]
    assert (truck["assigned_cases"], truck["capacity_cases"]) == (58, 60)
    assert truck["remaining_cases"] == 2
    assert truck["at_capacity"] is False
    assert truck["stops"][0]["order_id"] == "O202"


def test_v2_dispatch_capacity_omitted_not_backfilled_when_row_is_unsafe():
    """An unsafe timeless row yields unknown capacity, never a later value."""
    body = _beat("rev08")
    truck = [v for v in body["current_day"]["dispatch"]["vehicles"]
             if v["vehicle_id"] == "TRUCK-02"][0]
    assert truck["capacity_cases"] is None
    assert truck["assigned_cases"] is None
    assert truck["remaining_cases"] is None
    # Unknown capacity cannot support a "not at capacity" claim.
    assert truck["at_capacity"] is None
    assert any(o["field"] == "current_day.vehicles"
               for o in body["projection_boundary"]["omitted_fields"])
    # The committed stop assignment is still authoritative and still shown.
    assert truck["stops"][0]["order_id"] == "O202"


def test_v2_dispatch_creates_no_positions_or_route_geometry():
    raw = blob(_beat("refusal")["current_day"]["dispatch"])
    for banned in ("latitude", "longitude", "lat\"", "lng", "bearing",
                   "geometry", "position", "heading"):
        assert banned not in raw, banned


# --- recovery explanation --------------------------------------------------
def test_v2_recovery_absent_before_allocation():
    for name in ("healthy", "custody"):
        assert _beat(name)["current_day"]["recovery"]["explanation"] is None, name


def test_v2_recovery_explanation_is_derived_and_marked_as_such():
    explanation = _beat("recovery")["current_day"]["recovery"]["explanation"]
    assert explanation["basis"] == "DETERMINISTIC_DERIVATION"
    assert explanation["cases_allocated"] == 40
    assert explanation["cases_short"] == 20
    assert explanation["cases_requested"] == 60
    # No model reasoning is persisted anywhere, so none may be claimed.
    assert explanation["persisted_agent_rationale"] is None


# --- recall intake ---------------------------------------------------------
def test_v2_recall_intake_absent_before_the_recall_exists():
    assert _beat("healthy")["recall_intake_as_of"] is None
    assert _beat("truckfail")["recall_intake_as_of"] is None


def test_v2_recall_intake_progresses_only_on_committed_evidence():
    early = {s["step"]: s["state"]
             for s in _beat("recall_received")["recall_intake_as_of"]["steps"]}
    assert early["INCIDENT_OPENED"] == "COMPLETED"
    assert early["MOVEMENT_BARRIER_ACTIVE"] == "PENDING"
    late = {s["step"]: s["state"]
            for s in _beat("refusal")["recall_intake_as_of"]["steps"]}
    assert all(state == "COMPLETED" for state in late.values())
    # Only terminal states exist; the runtime observes nothing in between.
    for name in ("recall_received", "refusal"):
        for step in _beat(name)["recall_intake_as_of"]["steps"]:
            assert step["state"] in {"COMPLETED", "PENDING"}


# --- bounded history / execution record ------------------------------------
def test_v2_history_never_contains_a_post_boundary_event():
    for name, as_of, next_day in CANONICAL_BEATS:
        body = project(as_of, include_next_day=next_day).json()
        for event in body["execution_evidence_as_of"]["history"]:
            assert datetime.fromisoformat(event["committed_at"]) <= as_of, name


def test_v2_history_is_ordered_bounded_and_tenant_scoped():
    history = _beat("refusal")["execution_evidence_as_of"]["history"]
    stamps = [e["committed_at"] for e in history]
    assert stamps == sorted(stamps)
    assert len(history) <= orchestrator_main.HISTORY_MAX_EVENTS
    assert all(e["receipt_id"].startswith("fixture-RCT-") for e in history)


def test_v2_history_records_the_refusal_as_denied_zero_mutations():
    refusal = [e for e in _beat("refusal")["execution_evidence_as_of"]["history"]
               if e["action_type"] == "RECORD_REFUSAL"][0]
    assert refusal["status"] == "DENIED"
    assert refusal["mutations_applied"] == 0


def test_v2_history_cap_applies_after_relevance_not_instead_of_it():
    """Volume of irrelevant receipts must not consume the bounded window.

    Relevance is decided first, so a flood of unrelated same-tenant commits
    neither appears nor crowds out the canonical record.
    """
    noise = [receipt(f"filler:{i}", "INC-UNRELATED", "SET_INCIDENT_STATUS", T(9, 0))
             for i in range(orchestrator_main.HISTORY_MAX_EVENTS + 25)]
    body = project(T(10, 13), db=_database(receipts=noise + ALL_RECEIPTS)).json()
    history = body["execution_evidence_as_of"]["history"]
    assert len(history) == len(ALL_RECEIPTS)
    assert not any("filler" in event["receipt_id"] for event in history)


# --- global boundary invariants -------------------------------------------
def test_v2_tomorrow_absent_unless_explicitly_requested():
    assert "next_day_draft" not in project(T(17, 0)).json()
    assert "next_day_draft" in project(T(17, 0), include_next_day=True).json()


def test_v2_refresh_is_byte_identical_for_a_fixed_as_of():
    first = project(T(10, 13)).content
    second = project(T(10, 13)).content
    assert first == second


def test_v2_every_new_surface_is_tenant_scoped():
    body = _beat("refusal")
    assert body["tenant_id"] == TENANT
    assert body["execution_evidence_as_of"]["custody_graph"]["tenant_id"] == TENANT
    other = _database()
    project(T(10, 13), db=other)
    for call in other.snapshot.return_value.__enter__.return_value.execute_sql.call_args_list:
        params = call.kwargs.get("params") or {}
        if "tenant" in params or "tenant_id" in params:
            assert params.get("tenant", params.get("tenant_id")) == TENANT


def test_v2_projection_performs_no_authoritative_write():
    db = _database()
    project(T(10, 13), db=db)
    snapshot = db.snapshot.return_value.__enter__.return_value
    for banned in ("execute_update", "batch_update", "insert", "update",
                   "insert_or_update", "commit", "delete"):
        assert not getattr(snapshot, banned).called, banned
    assert not db.batch.called
    assert not db.run_in_transaction.called


# ---------------------------------------------------------------------------
# REPAIR PASS — canonical exactness and adversarial scope isolation.
#
# The prior delta was rejected because the handler and its fixtures agreed with
# each other while both disagreed with docs/authority/resolved-baseline.md, and
# because four queries admitted foreign rows. These tests pin the canonical
# facts themselves and prove each query is scoped at the SQL/identity level.
# ---------------------------------------------------------------------------

# Adversarial rows: same tenant, same operating day, committed before the
# boundary, plausible revisions and action types — but foreign targets.
FOREIGN_PLAN = "PLAN-2026-08-14-OTHER-DEPOT"
FOREIGN_INCIDENT = "INC-9999-FOREIGN"

FOREIGN_APPROVAL_ROW = (
    "fixture-APR-FOREIGN", FOREIGN_PLAN, "rev07", "rev08",
    "fixture-diffhash-foreign",
    "projects/p/locations/l/keyRings/k/cryptoKeys/c/cryptoKeyVersions/9",
    T(8, 24),
    _json.dumps({"reroute_order_id": "X999", "reroute_cases": 999,
                 "reroute_target_vehicle": "TRUCK-99",
                 "pickup_order_id": "X998", "pickup_cases": 998}),
    "intruder@example.com", f"{TENANT}@{DAY}", T(20, 0),
)
FOREIGN_ALLOC_ROW = ("ALLOC-FOREIGN", FOREIGN_INCIDENT, "COMMITTED", T(10, 10),
                     "AGENCY-99", "LTC-9999", 999)
FOREIGN_SHORTFALL_ROW = ("SF-FOREIGN", FOREIGN_INCIDENT, "OPEN", T(10, 10),
                         "AGENCY-98", 888)
NEXT_DAY_CONSTRAINT_ROW = (NEXT_PLAN, "LOT_EXCLUSION",
                           "tomorrow inherits the barrier", T(9, 0))


def _adversarial_database():
    """Every canonical row plus one foreign row per leak surface."""
    return _database(
        approval_rows=list(APPROVAL_ROWS) + [FOREIGN_APPROVAL_ROW],
        alloc_rows=list(ALLOC_ROWS) + [FOREIGN_ALLOC_ROW],
        shortfall_rows=list(SHORTFALL_ROWS) + [FOREIGN_SHORTFALL_ROW],
        constraint_rows=list(CONSTRAINT_ROWS) + [NEXT_DAY_CONSTRAINT_ROW],
        receipts=(
            list(ALL_RECEIPTS) + [
                # same tenant and time, unrelated action
                receipt("housekeeping:rotate", "INC-UNRELATED",
                        "SET_INCIDENT_STATUS", T(10, 0)),
                # foreign incident, plausible matching action type
                receipt("status:PARTIALLY_CONTAINED", FOREIGN_INCIDENT,
                        "SET_INCIDENT_STATUS", T(10, 11)),
                # foreign plan revision commit
                receipt("plan:rev08", "INC-OTHER-DEPOT", "SAVE_PLAN_REVISION",
                        T(8, 24)),
                # future event, already excluded by the boundary
                receipt("status:CONTAINED", RECALL_INC, "SET_INCIDENT_STATUS",
                        T(23, 0)),
            ]
        ),
    )


# --- R1: canonical order / assignment exactness ----------------------------
def test_repair_canonical_rev08_orders_are_exact():
    body = project(T(10, 13)).json()
    rev08 = {c["order_id"]: c for c in body["current_day"]["commitments"]
             if c["revision"] == "rev08"}
    assert rev08["O202"]["cases"] == 22
    assert rev08["O202"]["vehicle"] == "TRUCK-02"
    # O203 is the partner pickup at 20 cases. O205 was never the pickup.
    assert rev08["O203"]["cases"] == 20
    assert rev08["O203"]["vehicle"] is None
    assert rev08["O205"]["cases"] == 21
    assert rev08["O205"]["vehicle"] == "TRUCK-02"


def test_repair_partner_pickup_is_retained_with_evidence_backed_type():
    """A null vehicle id is the pickup path, not a reason to drop the row."""
    dispatch = project(T(10, 13)).json()["current_day"]["dispatch"]
    pickups = {p["order_id"]: p for p in dispatch["partner_pickups"]}
    assert set(pickups) == {"O203"}
    assert pickups["O203"]["cases"] == 20
    assert pickups["O203"]["assignment_type"] == "PARTNER_PICKUP"
    assert pickups["O203"]["assigned_vehicle_id"] is None
    routed = {s["order_id"]: s for v in dispatch["vehicles"] for s in v["stops"]}
    assert "O203" not in routed
    assert routed["O202"]["assignment_type"] == "VEHICLE_ROUTED"


def test_repair_truck2_capacity_is_canonical_arithmetic():
    """58/60 is 36 existing plus O202's 22, not an asserted constant."""
    assert CANONICAL_CAPACITY["truck_2_existing_cases"] == 36
    assert CANONICAL_CAPACITY["order_202_cases"] == 22
    truck = [v for v in project(T(16, 30)).json()["current_day"]["dispatch"]["vehicles"]
             if v["vehicle_id"] == "TRUCK-02"][0]
    assert truck["assigned_cases"] == 58
    assert truck["capacity_cases"] == 60
    assert truck["remaining_cases"] == 2
    # Routing O203 too would have been 78 against a 60 limit.
    assert CANONICAL_CAPACITY["total_cases_if_both_routed"] == 78
    assert CANONICAL_CAPACITY["result"] == "INFEASIBLE_EXCEEDS_CAPACITY"


def test_repair_approval_diff_is_the_canonical_o203_pickup():
    approval = project(T(8, 24)).json()["current_day"]["approvals"][0]
    changes = {row["change_type"]: row for row in approval["plan_diff"]}
    assert changes["REROUTE"] == {"change_type": "REROUTE", "order_id": "O202",
                                  "cases": 22, "target_vehicle": "TRUCK-02"}
    assert changes["PICKUP"]["order_id"] == "O203"
    assert changes["PICKUP"]["cases"] == 20
    assert "O205" not in blob(approval)


# --- R1: canonical custody node / edge exactness ---------------------------
def test_repair_custody_nodes_match_canonical_authority_exactly():
    graph = project(T(10, 13)).json()["execution_evidence_as_of"]["custody_graph"]
    positions = {n["node_id"]: n for n in graph["current_positions"]}
    assert {n: p["on_hand_cases"] for n, p in positions.items()} == {
        "N-WH": 24, "N-TR2": 22, "N-STG": 20,
        "N-AG01": 10, "N-ST01": 8, "N-RESC": 12,
    }
    assert positions["N-WH"]["node_type"] == "WAREHOUSE"
    assert positions["N-TR2"]["node_type"] == "VEHICLE"
    assert positions["N-STG"]["node_type"] == "STAGING"
    assert positions["N-ST01"]["node_type"] == "SUBSITE"
    assert positions["N-RESC"]["node_type"] == "DIRECT_RESCUE"
    # Only Site 01 is unconfirmed.
    assert [n for n, p in positions.items()
            if p["acknowledgment_status"] == "UNCONFIRMED"] == ["N-ST01"]


def test_repair_custody_edges_match_canonical_relationships_exactly():
    graph = project(T(10, 13)).json()["execution_evidence_as_of"]["custody_graph"]
    edges = {(e["source_node_id"], e["target_node_id"]): e for e in graph["edges"]}
    assert edges[("N-WH", "N-TR2")]["case_count"] == 22
    assert edges[("N-WH", "N-STG")]["case_count"] == 20
    assert edges[("N-WH", "N-AG01")]["case_count"] == 18
    assert edges[("N-WH", "N-RESC")]["case_count"] == 12
    # Site 01 hangs off Agency 01, and that is the only sub-distribution.
    assert edges[("N-AG01", "N-ST01")]["case_count"] == 8
    assert edges[("N-AG01", "N-ST01")]["is_sub_distribution"] is True
    assert [k for k, e in edges.items() if e["is_sub_distribution"]] == [
        ("N-AG01", "N-ST01")]


def test_repair_agency01_historical_receipt_is_not_its_current_position():
    """18 was received; 8 moved downstream; 10 is held now."""
    graph = project(T(10, 13)).json()["execution_evidence_as_of"]["custody_graph"]
    positions = {n["node_id"]: n for n in graph["current_positions"]}
    edges = {(e["source_node_id"], e["target_node_id"]): e for e in graph["edges"]}
    received = edges[("N-WH", "N-AG01")]["case_count"]
    passed_on = edges[("N-AG01", "N-ST01")]["case_count"]
    assert received == 18
    assert positions["N-AG01"]["on_hand_cases"] == received - passed_on == 10
    # The 18 must never be double counted into the unique total.
    assert graph["unique_current_cases"] == 96
    assert graph["intermediate_subtotals_readded"] is False


# --- R1/R3: canonical per-agency recovery ----------------------------------
def test_repair_recovery_is_exact_per_agency():
    recovery = project(T(10, 13)).json()["current_day"]["recovery"]
    assert {a["agency_id"]: a["cases"] for a in recovery["allocations"]} == {
        "AGENCY-01": 18, "AGENCY-02": 22}
    assert {s["agency_id"]: s["cases"] for s in recovery["shortfalls"]} == {
        "AGENCY-03": 20}


# --- R2: approval scope ----------------------------------------------------
def test_repair_foreign_plan_approval_is_absent_recursively():
    body = project(T(10, 13), db=_adversarial_database()).json()
    assert [a["plan_id"] for a in body["current_day"]["approvals"]] == [PLAN]
    raw = blob(body)
    for token in ("fixture-APR-FOREIGN", FOREIGN_PLAN, "X999", "X998",
                  "TRUCK-99", "intruder@example.com"):
        assert token not in raw, token


def test_repair_approval_is_bound_to_the_intended_revision_transition():
    """A same-plan approval of another transition is not this approval."""
    wrong_transition = ("fixture-APR-rev09", PLAN, "rev08", "rev09", "h", "kv",
                        T(8, 24), APPROVAL_DIFF, "operator@example.com",
                        f"{TENANT}@{DAY}", T(20, 0))
    body = project(T(10, 13),
                   db=_database(approval_rows=[wrong_transition])).json()
    assert body["current_day"]["approvals"] == []


# --- R3: recovery scope ----------------------------------------------------
def test_repair_foreign_incident_recovery_is_absent_from_every_block():
    body = project(T(10, 13), db=_adversarial_database()).json()
    recovery = body["current_day"]["recovery"]
    assert {a["agency_id"]: a["cases"] for a in recovery["allocations"]} == {
        "AGENCY-01": 18, "AGENCY-02": 22}
    assert {s["agency_id"]: s["cases"] for s in recovery["shortfalls"]} == {
        "AGENCY-03": 20}
    # The derivation runs over scoped rows, so it cannot be inflated.
    assert recovery["explanation"]["cases_allocated"] == 40
    assert recovery["explanation"]["cases_short"] == 20
    assert recovery["explanation"]["cases_requested"] == 60
    raw = blob(body)
    # Identifier tokens only. Bare quantities like "888" occur by coincidence
    # inside SHA-256 action identities, and substring matching on them would be
    # exactly the kind of prose-level check this repair is meant to remove.
    for token in ("ALLOC-FOREIGN", "SF-FOREIGN", FOREIGN_INCIDENT,
                  "AGENCY-99", "AGENCY-98"):
        assert token not in raw, token
    quantities = ([a["cases"] for a in recovery["allocations"]]
                  + [s["cases"] for s in recovery["shortfalls"]])
    assert 999 not in quantities and 888 not in quantities


def test_repair_foreign_incident_never_enters_carry_forward_obligations():
    body = project(T(10, 13), db=_adversarial_database()).json()
    for obligation in body["carry_forward_obligations"]:
        assert obligation.get("incident_id") != FOREIGN_INCIDENT
        assert "FOREIGN" not in blob(obligation)


# --- R4: plan-constraint scope --------------------------------------------
def test_repair_next_day_constraint_absent_from_current_day():
    """Committed before the boundary, but it belongs to tomorrow's plan."""
    body = project(T(10, 13), db=_adversarial_database()).json()
    assert [c["plan_id"] for c in body["current_day"]["plan_constraints"]] == [PLAN]
    assert NEXT_PLAN not in blob(body["current_day"])
    assert "tomorrow inherits the barrier" not in blob(body)


def test_repair_next_day_constraint_still_absent_when_draft_requested():
    """Requesting the draft exposes the draft, not tomorrow's constraints."""
    body = project(T(17, 0), db=_adversarial_database(),
                   include_next_day=True).json()
    assert [c["plan_id"] for c in body["current_day"]["plan_constraints"]] == [PLAN]
    assert body["next_day_draft"]["plan_id"] == NEXT_PLAN


# --- R5: history relevance -------------------------------------------------
def test_repair_history_admits_only_identity_linked_receipts():
    body = project(T(10, 13), db=_adversarial_database()).json()
    history = body["execution_evidence_as_of"]["history"]
    assert [e["receipt_id"] for e in history] == [
        f"fixture-RCT-{action}" for action, *_ in (
            ("plan:rev07",), ("status:SCOPING",), ("plan:rev08",),
            ("status:SCOPING",), ("movement-barrier",),
            ("status:CONTAINMENT_IN_PROGRESS",), ("plan:invalidate",),
            ("safe-recovery",), ("containment-refusal",),
            ("status:PARTIALLY_CONTAINED",),
        )
    ]
    raw = blob(history)
    for token in ("housekeeping", FOREIGN_INCIDENT, "INC-UNRELATED",
                  "INC-OTHER-DEPOT"):
        assert token not in raw, token


def test_repair_history_excludes_plausible_matching_action_with_foreign_target():
    """Right action type, right time, wrong incident: still absent."""
    body = project(T(10, 13), db=_adversarial_database()).json()
    history = body["execution_evidence_as_of"]["history"]
    assert [e for e in history if e["action_type"] == "SET_INCIDENT_STATUS"], (
        "canonical lifecycle receipts must survive relevance filtering")
    # Every admitted receipt must be recomputable from a selected incident.
    selected = {RECALL_INC, TRUCK_INC}
    recomputable = set()
    for incident_id in selected:
        for status in ("SCOPING", "CONTAINMENT_IN_PROGRESS",
                       "PARTIALLY_CONTAINED", "CONTAINED", "CLOSED"):
            recomputable.add(orchestrator_main._incident_status_action_id(
                TENANT, incident_id, status))
        for action in ("movement-barrier", "plan:invalidate", "safe-recovery",
                       "containment-refusal", "acknowledgment-hold",
                       "plan:rev07", "plan:rev08"):
            recomputable.add(orchestrator_main._incident_action_id(
                TENANT, incident_id, action))
    for event in history:
        assert event["action_id"] in recomputable, event["receipt_id"]



def test_repair_history_never_admits_a_future_receipt():
    body = project(T(10, 13), db=_adversarial_database()).json()
    for event in body["execution_evidence_as_of"]["history"]:
        assert datetime.fromisoformat(event["committed_at"]) <= T(10, 13)
    assert "status:CONTAINED" not in blob(body)


def test_repair_history_ordering_is_deterministic_by_timestamp_then_id():
    history = project(T(10, 13), db=_adversarial_database()).json()[
        "execution_evidence_as_of"]["history"]
    keys = [(e["committed_at"], e["receipt_id"]) for e in history]
    assert keys == sorted(keys)


# --- aggregate invariants retained ----------------------------------------
def test_repair_aggregate_invariants_still_hold():
    body = project(T(10, 13), db=_adversarial_database()).json()
    graph = body["execution_evidence_as_of"]["custody_graph"]
    assert (graph["unique_current_cases"], graph["confirmed_cases"],
            graph["unconfirmed_cases"]) == (96, 88, 8)
    explanation = body["current_day"]["recovery"]["explanation"]
    assert (explanation["cases_allocated"], explanation["cases_short"]) == (40, 20)
    recall = [i for i in body["current_day"]["incidents"]
              if i["incident_id"] == RECALL_INC][0]
    assert recall["terminal_state"] == "PARTIALLY_CONTAINED"
    assert recall["refusal"]["decision"] == "DENIED"
    assert recall["refusal"]["mutations_applied"] == 0


# ---------------------------------------------------------------------------
# B5: candidate next-day schedule, read from committed child Orders.
# ---------------------------------------------------------------------------

def _draft(as_of=T(17, 0)):
    return project(as_of, include_next_day=True,
                   db=_database(include_next_day=True)).json()["next_day_draft"]


def test_candidate_assignments_are_absent_before_the_draft_commits():
    """Requirement 1: nothing candidate is visible before its receipt."""
    body = project(T(16, 59), include_next_day=True,
                   db=_database(include_next_day=True)).json()
    assert "next_day_draft" not in body
    assert NEXT_PLAN not in blob(body)
    # Identity tokens, not the bare word: an unrelated agent validation label
    # ("CANDIDATE_ID_RESOLVED_DETERMINISTICALLY") legitimately contains it.
    raw = blob(body)
    for row in CANDIDATE_ORDER_ROWS:
        assert row[1] not in raw


def test_candidate_rows_are_read_not_recomputed():
    """Requirement 2: the projection reports exactly the stored rows."""
    draft = _draft()
    stored = {row[1]: row for row in CANDIDATE_ORDER_ROWS}
    projected = [stop for vehicle in draft["candidate_vehicles"]
                 for stop in vehicle["stops"]]
    assert len(projected) == len(stored)
    for stop in projected:
        row = stored[stop["order_id"]]
        assert (stop["agency"], stop["cases"], stop["lot_id"]) == (
            row[2], row[3], row[4])
        assert stop["status"] == "CANDIDATE"


def test_current_day_excludes_every_saturday_candidate_row():
    """Requirement 3: no candidate row may appear in Friday's projection."""
    body = project(T(23, 59), include_next_day=True,
                   db=_database(include_next_day=True)).json()
    current = blob(body["current_day"])
    assert NEXT_PLAN not in current
    for row in CANDIDATE_ORDER_ROWS:
        assert row[1] not in current
    for commitment in body["current_day"]["commitments"]:
        assert commitment["status"] != "CANDIDATE"
    # Friday's own commitments are untouched and still revision-gated.
    assert {c["order_id"] for c in body["current_day"]["commitments"]} == {
        "O201", "O202", "O203", "O204", "O205"}


def test_current_day_dispatch_never_carries_a_candidate_stop():
    dispatch = project(T(23, 59), include_next_day=True,
                       db=_database(include_next_day=True)
                       ).json()["current_day"]["dispatch"]
    for vehicle in dispatch["vehicles"]:
        for stop in vehicle["stops"]:
            assert stop["status"] != "CANDIDATE"
            assert not stop["order_id"].startswith("CAND-")


def test_excluded_recalled_lot_never_enters_the_candidate_plan():
    """Requirement 4: LTC-4471 is under an active barrier."""
    draft = _draft()
    for vehicle in draft["candidate_vehicles"]:
        for stop in vehicle["stops"]:
            assert stop["lot_id"] != "LTC-4471"
    assert "LTC-4471" not in blob(draft["candidate_vehicles"])


def test_candidate_vehicle_load_does_not_exceed_capacity():
    """Requirement 5: stored loads respect the authoritative capacity."""
    capacity = {row[0]: row[2] for row in VEHICLE_ROWS}
    for vehicle in _draft()["candidate_vehicles"]:
        limit = capacity.get(vehicle["vehicle_id"])
        if limit is not None:
            assert vehicle["candidate_load_cases"] <= limit
        assert vehicle["candidate_load_cases"] == sum(
            stop["cases"] for stop in vehicle["stops"])


def test_agency_03_remains_explicitly_unassigned():
    """Requirement 9: the canonical carried obligation stays truthful."""
    draft = _draft()
    unassigned = draft["unassigned_demand"]
    assert len(unassigned) == 1
    assert unassigned[0]["agency_id"] == "AGENCY-03"
    assert unassigned[0]["cases"] == 20
    # And it is never quietly scheduled instead.
    scheduled = {stop["agency_id"] for vehicle in draft["candidate_vehicles"]
                 for stop in vehicle["stops"]}
    assert "AGENCY-03" not in scheduled


def test_canonical_saturday_candidate_result_is_truthful():
    """Requirement 9: 18 + 22 scheduled, 20 short, on one refrigerated truck."""
    draft = _draft()
    assert draft["status"] == "DRAFT_WITH_CONSTRAINTS"
    assert draft["approval_required"] is True
    stops = [stop for vehicle in draft["candidate_vehicles"]
             for stop in vehicle["stops"]]
    assert sorted(stop["cases"] for stop in stops) == [18, 22]
    assert sum(stop["cases"] for stop in stops) == 40
    assert draft["unassigned_demand"][0]["cases"] == 20


def test_draft_exposes_no_activation_path():
    """Requirement 8: a candidate can never be activated from this surface."""
    draft = _draft()
    assert draft["activation_supported"] is False
    assert draft["status"] != "ACTIVE"
    for stop in (s for v in draft["candidate_vehicles"] for s in v["stops"]):
        assert stop["status"] == "CANDIDATE"
    raw = blob(draft)
    for token in ("ACTIVATE", "APPROVED", "\"ACTIVE\""):
        assert token not in raw, token
    # No control surface: the draft carries no action or endpoint field.
    assert not any(key.endswith(("_url", "_action", "_endpoint"))
                   for key in draft)


def test_candidate_stop_sequence_is_contiguous_per_vehicle():
    for vehicle in _draft()["candidate_vehicles"]:
        sequences = [stop["sequence"] for stop in vehicle["stops"]]
        assert sequences == list(range(1, len(sequences) + 1))


# ---------------------------------------------------------------------------
# Repair proposal lifecycle: proposed, pending, then answered.
# ---------------------------------------------------------------------------

def _proposal_at(as_of):
    return project(as_of).json()["current_day"]["repair_proposal"]


def test_repair_proposal_is_absent_before_the_fleet_proposes_one():
    """08:20 is the fault. The proposal does not exist yet."""
    assert _proposal_at(T(8, 20)) is None


def test_repair_proposal_is_pending_while_the_active_plan_is_unchanged():
    """At 08:21 the proposal exists and rev07 is STILL authoritative."""
    body = project(T(8, 21)).json()["current_day"]
    proposal = body["repair_proposal"]
    assert proposal is not None
    assert proposal["authority"] == "AGENT_PROPOSAL"
    assert proposal["approval_required"] is True
    assert proposal["activation_supported"] is False
    # The plan the operator is working from has not moved.
    assert body["active_plan_revision"] == "rev07"
    assert {c["revision"] for c in body["commitments"]} == {"rev07"}


def test_repair_proposal_carries_the_exact_candidate_diff():
    """O202/22 -> Truck 2 (36 + 22 = 58 of 60), O203/20 -> partner pickup."""
    proposal = _proposal_at(T(8, 21))
    diff = proposal["plan_diff"]
    assert diff["reroute_order_id"] == CANONICAL_APPROVAL["reroute_order_id"]
    assert diff["reroute_cases"] == CANONICAL_APPROVAL["reroute_cases"]
    assert diff["reroute_target_vehicle"] == CANONICAL_APPROVAL["reroute_target_vehicle"]
    assert diff["pickup_order_id"] == CANONICAL_APPROVAL["pickup_order_id"]
    assert diff["pickup_cases"] == CANONICAL_APPROVAL["pickup_cases"]
    absorbing = proposal["absorbing_vehicle"]
    assert absorbing["committed_cases"] == CANONICAL_CAPACITY["truck_2_existing_cases"]
    assert absorbing["projected_cases"] == TRUCK2_LOAD  # 58
    assert absorbing["capacity_cases"] == CANONICAL_CAPACITY["capacity_limit"]
    assert absorbing["projected_cases"] <= absorbing["capacity_cases"]


def test_repair_proposal_stops_being_offered_once_approved_and_activated():
    """After rev08 activates at 08:24 the proposal has been answered."""
    assert _proposal_at(T(8, 24)) is None
    assert _proposal_at(T(23, 59)) is None
    assert project(T(8, 24)).json()["current_day"]["active_plan_revision"] == "rev08"


def test_repair_proposal_binds_the_same_diff_the_approval_signs():
    """Proposal and approval must not be able to drift apart."""
    proposal = _proposal_at(T(8, 21))
    approval = project(T(8, 24)).json()["current_day"]["approvals"][0]
    signed = {(d["change_type"], d["order_id"], d["cases"]) for d in approval["plan_diff"]}
    assert ("REROUTE", proposal["plan_diff"]["reroute_order_id"],
            proposal["plan_diff"]["reroute_cases"]) in signed
    assert ("PICKUP", proposal["plan_diff"]["pickup_order_id"],
            proposal["plan_diff"]["pickup_cases"]) in signed


def test_refrigeration_failure_is_independent_of_simulated_position():
    """A mechanical fault is not derived from position, and carries none.

    The projection must expose no coordinate, bearing, speed or heading
    anywhere near the incident or the proposal it produced.
    """
    raw = blob(project(T(8, 21)).json())
    for token in ("latitude", "longitude", "bearing", "heading",
                  "speed", "gps", "coordinate"):
        assert token not in raw.lower(), token


def test_repair_proposal_is_not_reported_as_a_plan_constraint():
    """A proposal is not a committed constraint on the plan."""
    constraints = project(T(8, 21)).json()["current_day"]["plan_constraints"]
    assert all(c["constraint_type"] != "REPAIR_PROPOSAL" for c in constraints)


# ---------------------------------------------------------------------------
# Recall arrival, ordering, and truthful refusal terminology.
# ---------------------------------------------------------------------------

def test_regulatory_event_precedes_screening_and_extraction():
    """Authority order: event arrives, Model Armor screens, then extraction."""
    intake = project(T(10, 13)).json()["recall_intake_as_of"]
    steps = [s["step"] for s in intake["steps"]]
    assert steps.index("REGULATORY_EVENT_RECEIVED") < steps.index("NOTICE_SCREENED")
    assert steps.index("NOTICE_SCREENED") < steps.index("NOTICE_EXTRACTED")
    assert steps.index("NOTICE_EXTRACTED") < steps.index("INCIDENT_OPENED")


def test_recall_source_is_a_delivered_event_not_claimed_monitoring():
    """The demo input is a representative FDA-format notice, not a feed poll."""
    source = project(T(10, 13)).json()["recall_intake_as_of"]["source"]
    assert source["channel"] == "REGULATORY_FEED"
    assert source["notice_format"] == "FDA_FORMAT"
    assert source["input_kind"] == "REPRESENTATIVE_REGULATORY_EVENT"
    # Full Shelf does not poll or monitor the FDA and must never say it does.
    assert source["monitoring_claimed"] is False


def test_recall_source_records_the_committed_arrival_time():
    source = project(T(10, 13)).json()["recall_intake_as_of"]["source"]
    assert source["received_at"].startswith("2026-08-14T09:36")


def test_model_armor_is_a_boundary_not_a_sixth_agent():
    """Screening is an intake step; the fleet stays at five agents."""
    body = project(T(10, 13)).json()
    steps = [s["step"] for s in body["recall_intake_as_of"]["steps"]]
    assert "NOTICE_SCREENED" in steps
    agents = body["agent_activity_as_of"]["agents"]
    assert len(agents) == 5
    names = " ".join(a["display_name"] for a in agents).lower()
    assert "armor" not in names


def test_refusal_names_the_real_backend_action():
    """No DECLARE_CONTAINED: that command does not exist in the ledger."""
    incidents = project(T(10, 13)).json()["current_day"]["incidents"]
    refusal = next(i["refusal"] for i in incidents if i["refusal"])
    assert refusal["requested_action"] == "CLOSURE_ELIGIBILITY_CHECK"
    assert refusal["policy_action"] == "RECORD_REFUSAL"
    assert refusal["decided_by"] == "DETERMINISTIC_POLICY"
    assert refusal["decision"] == "DENIED"
    assert refusal["mutations_applied"] == 0
    assert "DECLARE_CONTAINED" not in blob(project(T(10, 13)).json())


def test_refused_closure_leaves_the_incident_partially_contained():
    incidents = project(T(23, 59)).json()["current_day"]["incidents"]
    recall = next(i for i in incidents if i["incident_id"] == RECALL_INC)
    assert recall["status"] == "PARTIALLY_CONTAINED"
    assert recall["terminal_state"] == "PARTIALLY_CONTAINED"
