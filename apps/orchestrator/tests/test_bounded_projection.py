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
    return (f"RCT-{action}", action_id(incident_id, action), action_type,
            status, mutations, ts)


# Canonical Friday receipt ledger, in real commit order.
ALL_RECEIPTS = [
    receipt("plan:rev07", TRUCK_INC, "SAVE_PLAN_REVISION", T(7, 30)),
    receipt("status:SCOPING", TRUCK_INC, "SET_INCIDENT_STATUS", T(8, 20)),
    receipt("plan:rev08", TRUCK_INC, "SAVE_PLAN_REVISION", T(8, 24)),
    receipt("status:SCOPING", RECALL_INC, "SET_INCIDENT_STATUS", T(9, 36)),
    receipt("movement-barrier", RECALL_INC, "ACTIVATE_MOVEMENT_BARRIER", T(10, 5)),
    receipt("status:CONTAINMENT_IN_PROGRESS", RECALL_INC, "SET_INCIDENT_STATUS", T(10, 6)),
    receipt("safe-recovery", RECALL_INC, "ALLOCATE_SAFE_STOCK", T(10, 10)),
    receipt("containment-refusal", RECALL_INC, "RECORD_REFUSAL", T(10, 12),
            status="DENIED", mutations=0),
    receipt("status:PARTIALLY_CONTAINED", RECALL_INC, "SET_INCIDENT_STATUS", T(10, 13)),
]

FLEET = {
    "manifest_version": "1.1.0",
    "root_agent_id": "full-shelf.incident-coordinator.v1",
    "coordinator_session_id": "sess-coord-1",
    "coordination_run_id": "run-coord-1",
    "proposal_status": "PROPOSED",
    "proposal_hash": "abc123",
    "delegation_trace": [{"agent_id": "full-shelf.recall-extraction.v1",
                          "specialist_run_id": "run-recall-1"}],
}

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
SHORTFALL_ROWS = [("SF-A03", RECALL_INC, "OPEN", T(10, 10))]
ALLOC_ROWS = [("ALLOC-1", RECALL_INC, "COMMITTED", T(10, 10))]
CONSTRAINT_ROWS = [(PLAN, "LOT_EXCLUSION", "LTC-4471 excluded", T(10, 5))]


def _database(*, include_next_day=False, vehicles=VEHICLE_ROWS,
              work_rows=WORK_ROWS, incident_rows=INCIDENT_ROWS,
              receipts=ALL_RECEIPTS):
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
            return []
        if "FROM Incidents" in sql:
            return [r for r in incident_rows if as_of is None or r[6] <= as_of]
        if "FROM MovementBarriers" in sql:
            return [r for r in BARRIER_ROWS if as_of is None or r[3] <= as_of]
        if "FROM RecoveryAllocations" in sql:
            return [r for r in ALLOC_ROWS if as_of is None or r[3] <= as_of]
        if "FROM RecoveryShortfalls" in sql:
            return [r for r in SHORTFALL_ROWS if as_of is None or r[3] <= as_of]
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
    url = f"/api/v1/projections/demo-beats?as_of={quote(as_of.isoformat())}"
    if include_next_day:
        url += "&include_next_day_draft=true"
    # Override the FastAPI dependency by key. Patching the module attribute is
    # not enough: the route already captured the original callable at import.
    orchestrator_main.app.dependency_overrides[
        orchestrator_main.require_frontend_authority
    ] = lambda: (identity, scope, DAY)
    with (
        patch.object(orchestrator_main, "get_spanner_database",
                     return_value=db if db is not None else _database()),
        patch.object(orchestrator_main, "_run_managed_custody_graph",
                     return_value={"lot_id": "LTC-4471", "unique_current_cases": 96,
                                   "confirmed_cases": 88, "unconfirmed_cases": 8}),
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
    assert fleet["coordination_run_id"] == "run-coord-1"
    assert fleet["proposal_status"] == "PROPOSED"
    assert fleet["delegation_trace"][0]["specialist_run_id"] == "run-recall-1"


def test_delta3_sse_receipt_projection_carries_mutations_applied():
    row = ("RCT-1", "CMD-1", "rev08", "RECORD_REFUSAL", "DENIED", "refused",
           T(10, 12), CORRELATION, "op@example.com", 0)
    projected = orchestrator_main._receipt_projection(row)
    assert projected["status"] == "DENIED"
    assert projected["mutations_applied"] == 0
