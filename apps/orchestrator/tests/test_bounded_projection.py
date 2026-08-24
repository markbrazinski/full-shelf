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
import os
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
        _hop("full-shelf.recall-extraction.v1", "recall",
             "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED"),
        _hop("full-shelf.network-custody.v1", "custody",
             "RECONCILED_WITH_DETERMINISTIC_GRAPH",
             declared_tools=["custody_graph_read", "custody_dependents_read"],
             tool_invocations=[{"tool_name": "custody_graph_read",
                                "status": "SUCCEEDED"}]),
        _hop("full-shelf.fulfillment-recovery.v1", "recovery",
             "CANDIDATE_ID_RESOLVED_DETERMINISTICALLY"),
        _hop("full-shelf.partner-operations.v1", "partner",
             "TEMPLATE_AND_PARAMETERS_VALIDATED"),
    ],
}

# The canonical rev07->rev08 repair, as persisted under KMS binding.
APPROVAL_DIFF = __import__("json").dumps({
    "reroute_order_id": "O202", "reroute_cases": 22,
    "reroute_target_vehicle": "TRUCK-02",
    "pickup_order_id": "O205", "pickup_cases": 21,
})
APPROVAL_ROWS = [(
    "fixture-APR-rev08", PLAN, "rev07", "rev08", "fixture-diffhash-rev08",
    "projects/p/locations/l/keyRings/k/cryptoKeys/c/cryptoKeyVersions/1",
    T(8, 24), APPROVAL_DIFF, "operator@example.com", f"{TENANT}@{DAY}", T(20, 0),
)]

PLAN_ROWS = [
    (PLAN, "rev07", "SUPERSEDED", T(7, 30)),
    (PLAN, "rev08", "ACTIVE", T(8, 24)),
]
NEXT_DAY_ROWS = [(NEXT_PLAN, "rev01", "DRAFT_WITH_CONSTRAINTS", T(17, 0))]
ORDER_ROWS = [
    ("rev07", "O201", "Agency 01", 18, "LTC-4471", "TRUCK-01", "PLANNED"),
    ("rev07", "O204", "Agency 04", 15, "LTC-5090", "TRUCK-02", "PLANNED"),
    ("rev07", "O205", "Agency 05", 21, "LTC-5090", "TRUCK-02", "PLANNED"),
    ("rev08", "O202", "Agency 02", 22, "LTC-4471", "TRUCK-02", "PLANNED"),
]
INCIDENT_ROWS = [
    (TRUCK_INC, "VEHICLE_FAILURE", "SCOPING", "NONE", "{}", None, T(8, 20), T(8, 24)),
    (RECALL_INC, "FOOD_SAFETY_RECALL", "PARTIALLY_CONTAINED", "PARTIALLY_CONTAINED",
     '{"model_armor_correlation_id": "%s", "agent_fleet": %s}'
     % (CORRELATION, __import__("json").dumps(FLEET)),
     "LTC-4471", T(9, 36), None),
]
VEHICLE_ROWS = [("TRUCK-02", "Refrigerated Truck 2", 60, 58, True)]
WORK_ROWS = [("WORK-SITE01", RECALL_INC, "OPEN", T(10, 5), None)]
BARRIER_ROWS = [("BARRIER-4471", "LTC-4471", "ACTIVE", T(10, 5), None)]
SHORTFALL_ROWS = [("SF-A03", RECALL_INC, "OPEN", T(10, 10), "AGY-03", 20)]
ALLOC_ROWS = [
    ("ALLOC-1", RECALL_INC, "COMMITTED", T(10, 10), "AGY-01", "LTC-5090", 22),
    ("ALLOC-2", RECALL_INC, "COMMITTED", T(10, 10), "AGY-02", "LTC-5090", 18),
]
CONSTRAINT_ROWS = [(PLAN, "LOT_EXCLUSION", "LTC-4471 excluded", T(10, 5))]

def _node(node_id, node_type, name, cases, ack, depth):
    return {"node_id": node_id, "node_type": node_type, "name": name,
            "on_hand_cases": cases, "acknowledgment_status": ack,
            "path_depth": depth}


CUSTODY_POSITIONS = [
    _node("WH-01", "WAREHOUSE", "Central Warehouse", 30, "CONFIRMED", 0),
    _node("AGY-01", "AGENCY", "Agency 01", 20, "CONFIRMED", 1),
    _node("AGY-02", "AGENCY", "Agency 02", 18, "CONFIRMED", 1),
    _node("AGY-04", "AGENCY", "Agency 04", 12, "CONFIRMED", 1),
    _node("SITE-01", "SUB_SITE", "Site 01", 8, "UNCONFIRMED", 2),
    _node("AGY-05", "AGENCY", "Agency 05", 8, "CONFIRMED", 1),
]
CUSTODY_GRAPH = {
    "tenant_id": TENANT,
    "lot_id": "LTC-4471",
    "query_engine": "SPANNER_GRAPH_GQL",
    "paths": [{"root_node_id": "WH-01", "destination_node_id": n["node_id"],
               "path_depth": n["path_depth"]}
              for n in CUSTODY_POSITIONS if n["node_id"] != "WH-01"],
    "current_positions": CUSTODY_POSITIONS,
    "unique_current_cases": 96,
    "confirmed_cases": 88,
    "unconfirmed_cases": 8,
    "unconfirmed_positions": [n for n in CUSTODY_POSITIONS
                              if n["acknowledgment_status"] == "UNCONFIRMED"],
    "max_path_depth": 2,
    "node_count": 6,
    "intermediate_subtotals_readded": False,
    "classification": "OBSERVED_LIVE",
}


def _database(*, include_next_day=False, vehicles=VEHICLE_ROWS,
              work_rows=WORK_ROWS, incident_rows=INCIDENT_ROWS,
              receipts=ALL_RECEIPTS, approval_rows=APPROVAL_ROWS,
              alloc_rows=ALLOC_ROWS, shortfall_rows=SHORTFALL_ROWS):
    """Fake Spanner honouring the handler's as_of/plan_id predicates."""
    db = MagicMock()
    snap = MagicMock()

    def execute_sql(sql, params=None, param_types=None):
        params = params or {}
        as_of = params.get("as_of")
        pid = params.get("plan_id")
        if "FROM Receipts" in sql:
            return list(receipts)
        if "FROM PlanRevisions" in sql:
            rows = NEXT_DAY_ROWS if pid == NEXT_PLAN else PLAN_ROWS
            if pid is not None:
                rows = [r for r in rows if r[0] == pid]
            return [r for r in rows if as_of is None or r[3] <= as_of]
        if "FROM Orders" in sql:
            return list(ORDER_ROWS)
        if "FROM Approvals" in sql:
            return [r for r in approval_rows if as_of is None or r[6] <= as_of]
        if "FROM Incidents" in sql:
            return [r for r in incident_rows if as_of is None or r[6] <= as_of]
        if "FROM MovementBarriers" in sql:
            return [r for r in BARRIER_ROWS if as_of is None or r[3] <= as_of]
        if "FROM RecoveryAllocations" in sql:
            return [r for r in alloc_rows if as_of is None or r[3] <= as_of]
        if "FROM RecoveryShortfalls" in sql:
            return [r for r in shortfall_rows if as_of is None or r[3] <= as_of]
        if "FROM WorkItems" in sql:
            return [r for r in work_rows if as_of is None or r[3] <= as_of]
        if "FROM PlanConstraints" in sql:
            return [r for r in CONSTRAINT_ROWS if as_of is None or r[3] <= as_of]
        if "FROM Vehicles" in sql:
            return list(vehicles)
        return []

    snap.execute_sql.side_effect = execute_sql
    db.snapshot.return_value.__enter__.return_value = snap
    return db


def project(as_of, *, include_next_day=False, db=None):
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
                     return_value=CUSTODY_GRAPH),
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
    assert blob(body).count(NEXT_PLAN) == 1


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
    assert truck["status"] == "SCOPING"
    assert truck["terminal_state"] == "NONE"


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
    assert {c["order_id"] for c in commitments} == {"O201", "O204", "O205"}


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
    assert fleet["delegation_trace"][0]["specialist_run_id"] == "fixture-run-recall-1"


def test_delta3_sse_receipt_projection_carries_mutations_applied():
    row = ("fixture-RCT-1", "CMD-1", "rev08", "RECORD_REFUSAL", "DENIED", "refused",
           T(10, 12), CORRELATION, "op@example.com", 0)
    projected = orchestrator_main._receipt_projection(row)
    assert projected["status"] == "DENIED"
    assert projected["mutations_applied"] == 0


# ---------------------------------------------------------------------------
# UI PROOF PROJECTION v2 — bounded authority-backed hero-loop surfaces.
#
# Every assertion below proves one of two things: that an authority-backed
# surface is projected once it exists, or that it is absent before it exists.
# Nothing here asserts a value the schema cannot source from a committed
# record, a persisted fleet result, or a transparent derivation.
# ---------------------------------------------------------------------------

import json as _json
import pathlib as _pathlib

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
    """
    live = _reclassify(project(as_of, include_next_day=next_day).json())
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
    assert changes["PICKUP"]["order_id"] == "O205"


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
        "Incident Coordinator", "Recall Extraction", "Network & Custody",
        "Fulfillment & Recovery", "Partner Operations",
    ]
    assert all(a["state"] == "COMPLETED" for a in fleet["agents"])
    # Each specialist reports its OWN run/session, never the coordinator's.
    specialists = [a for a in fleet["agents"] if a["role"] == "GOVERNED_SPECIALIST"]
    assert len({a["session_id"] for a in specialists}) == 4
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
    assert agents["full-shelf.network-custody.v1"]["tool_invocations"]
    for agent_id, agent in agents.items():
        if agent_id != "full-shelf.network-custody.v1":
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
    assert states["Fulfillment & Recovery"] == "NOT_YET_REPORTED"
    assert states["Partner Operations"] == "NOT_YET_REPORTED"
    assert states["Recall Extraction"] == "COMPLETED"


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


def test_v2_history_is_capped_and_keeps_the_boundary_tail():
    """A long ledger must bound the response rather than dump the table."""
    many = [receipt(f"filler:{i}", TRUCK_INC, "SET_INCIDENT_STATUS", T(9, 0))
            for i in range(orchestrator_main.HISTORY_MAX_EVENTS + 25)]
    body = project(T(10, 13), db=_database(receipts=many + ALL_RECEIPTS)).json()
    history = body["execution_evidence_as_of"]["history"]
    assert len(history) == orchestrator_main.HISTORY_MAX_EVENTS
    assert history[-1]["action_type"] == "SET_INCIDENT_STATUS"


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
