"""Coordinator delegation, canonical preservation, and refusal behavior.

The fleet sequence is driven with a scripted runner so delegation order,
evidence assembly, and every failure path are provable without a live model.
"""

import pytest

from full_shelf_domain.fleet.contracts import (
    AGENT_FULFILLMENT_RECOVERY,
    AGENT_INCIDENT_COORDINATOR,
    AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
    AGENT_RECALL_EXTRACTION,
    FleetProposalError,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
)
from full_shelf_domain.fleet.coordinator import run_fleet
from full_shelf_domain.fleet.tools import generate_recovery_candidates

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_fleet_validation import CANONICAL_GRAPH  # noqa: E402


CANONICAL_CANDIDATES = generate_recovery_candidates(
    incident_id="INC-CANON",
    safe_lots=[("LTC-5090", 40)],
    affected_orders=[("O201", "AG-01", 18), ("O202", "AG-02", 22),
                     ("O203", "AG-03", 20)],
)

PARTNER_STATE = {
    "partner_id": "SITE-01", "partner_name": "Site 01", "lot_id": "LTC-4471",
    "unconfirmed_cases": 8, "acknowledgment_status": "UNCONFIRMED",
    "deadline": "2026-08-08T17:00:00Z",
}

EXTRACTION_EVIDENCE = {
    "model_used": "gemini-3.5-flash",
    "adk_framework": "google-adk/1.14.1",
    "adk_session_id": "recall-session",
    "adk_run_id": "recall-run",
    "adk_event_id": "recall-event",
    "validation_status": "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED",
}


def outputs(*, custody=None, recovery=None, partner=None, candidate_id="CAND-LOT-ASC"):
    custody = custody or NetworkCustodyAssessment(
        lot_id="LTC-4471", total_cases_in_custody=96, confirmed_cases=88,
        unconfirmed_cases=8, unconfirmed_node_ids=["SITE-01"], max_path_depth=3,
        containment_assessment="UNCONFIRMED_DOWNSTREAM",
        narrative="Site 01 has not confirmed eight cases.",
    )
    recovery = recovery or RecoverySelection(
        selected_candidate_id=candidate_id,
        rationale="Serves both agencies fully from available safe stock.",
        cited_constraints=["40 safe cases available"],
        tradeoffs="A truthful shortfall remains.", confidence=0.9,
    )
    partner = partner or PartnerCommunication(
        partner_id="SITE-01", template_id="partner.acknowledgment-request.v1",
        escalation_level="URGENT",
        template_parameters={
            "partner_name": "Site 01", "lot_id": "LTC-4471", "cases": "8",
            "deadline": "2026-08-08T17:00:00Z",
        },
        rationale="Custody unconfirmed with a deadline.", confidence=0.9,
    )
    return {
        AGENT_NETWORK_CUSTODY: custody,
        AGENT_FULFILLMENT_RECOVERY: recovery,
        AGENT_PARTNER_OPERATIONS: partner,
    }


def scripted_runner(scripted, *, calls=None, fail=None):
    """Return a runner that replays scripted outputs and records call order."""

    def _runner(*, agent, agent_id, prompt, output_model, timeout_seconds=None):
        if calls is not None:
            calls.append(agent_id)
        if fail and fail[0] == agent_id:
            raise FleetProposalError(fail[1], agent_id)
        return {
            "output": scripted[agent_id],
            "execution": {
                "agent_id": agent_id, "agent_name": agent.name,
                "model_used": "gemini-3.5-flash",
                "adk_framework": "google-adk/1.14.1",
                "adk_session_id": f"session-{agent_id}",
                "adk_run_id": f"run-{agent_id}",
                "adk_event_id": f"event-{agent_id}",
                "declared_tools": [], "tool_invocations": [],
            },
        }

    return _runner


def run_canonical(**kwargs):
    return run_fleet(
        incident_id="INC-CANON", lot_id="LTC-4471",
        graph_result=CANONICAL_GRAPH, recovery_candidates=CANONICAL_CANDIDATES,
        partner_state=PARTNER_STATE, extraction_evidence=EXTRACTION_EVIDENCE,
        **kwargs,
    )


# --- Delegation -------------------------------------------------------------


def test_root_delegates_to_all_four_specialists_in_order():
    calls = []
    result = run_canonical(runner=scripted_runner(outputs(), calls=calls))
    assert result["proposal"].status == "PROPOSED"
    assert calls == [
        AGENT_NETWORK_CUSTODY,
        AGENT_FULFILLMENT_RECOVERY,
        AGENT_PARTNER_OPERATIONS,
    ]
    traced = [entry["agent_id"] for entry in result["proposal"].delegation_trace]
    assert traced == [
        AGENT_RECALL_EXTRACTION,
        AGENT_NETWORK_CUSTODY,
        AGENT_FULFILLMENT_RECOVERY,
        AGENT_PARTNER_OPERATIONS,
    ]
    assert all(
        entry["parent_agent_id"] == AGENT_INCIDENT_COORDINATOR
        for entry in result["proposal"].delegation_trace
    )


def test_delegation_trace_carries_adk_identifiers_and_validation_results():
    result = run_canonical(runner=scripted_runner(outputs()))
    for entry in result["proposal"].delegation_trace:
        assert entry["adk_session_id"]
        assert entry["adk_run_id"]
        assert entry["adk_framework"].startswith("google-adk/")
        assert entry["deterministic_validation"]


def test_delegation_trace_contains_no_prompt_or_model_text():
    result = run_canonical(runner=scripted_runner(outputs()))
    serialized = str(result["proposal"].delegation_trace)
    for leaked in ("Assess custody", "Select exactly one candidate",
                   "Partner state:", "instruction"):
        assert leaked not in serialized


def test_proposal_hash_is_stable_and_present():
    first = run_canonical(runner=scripted_runner(outputs()))
    second = run_canonical(runner=scripted_runner(outputs()))
    assert first["proposal"].proposal_hash
    assert first["proposal"].proposal_hash == second["proposal"].proposal_hash


# --- Canonical preservation -------------------------------------------------


def test_canonical_recovery_contents_are_unchanged_by_the_fleet():
    result = run_canonical(runner=scripted_runner(outputs()))
    candidate = result["recovery_candidate"]
    assert [(a["agency_id"], a["cases"]) for a in candidate["allocations"]] == [
        ("AG-01", 18), ("AG-02", 22)
    ]
    assert [(s["agency_id"], s["cases"]) for s in candidate["shortfalls"]] == [
        ("AG-03", 20)
    ]
    assert result["proposal"].custody.total_cases_in_custody == 96
    assert result["proposal"].custody.confirmed_cases == 88
    assert result["proposal"].custody.unconfirmed_cases == 8
    assert result["proposal"].custody.containment_assessment == (
        "UNCONFIRMED_DOWNSTREAM"
    )


def test_canonical_scenario_gives_the_planner_no_discretion():
    # One truthful candidate means the model cannot alter the accepted result.
    assert [c["candidate_id"] for c in CANONICAL_CANDIDATES] == ["CAND-LOT-ASC"]


# --- Noncanonical variation -------------------------------------------------


def test_noncanonical_selection_changes_the_proposal_while_staying_valid():
    candidates = generate_recovery_candidates(
        incident_id="INC-ALT",
        safe_lots=[("LTS-100", 15), ("LTS-200", 30)],
        affected_orders=[("OA", "AG-A", 20), ("OB", "AG-B", 30)],
    )
    graph = dict(CANONICAL_GRAPH, lot_id="LTS-RECALL")
    partner_state = dict(PARTNER_STATE, lot_id="LTS-RECALL")

    def run_with(candidate_id):
        scripted = outputs(
            custody=NetworkCustodyAssessment(
                lot_id="LTS-RECALL", total_cases_in_custody=96,
                confirmed_cases=88, unconfirmed_cases=8,
                unconfirmed_node_ids=["SITE-01"], max_path_depth=3,
                containment_assessment="UNCONFIRMED_DOWNSTREAM",
                narrative="Unconfirmed downstream custody remains.",
            ),
            candidate_id=candidate_id,
            partner=PartnerCommunication(
                partner_id="SITE-01",
                template_id="partner.acknowledgment-request.v1",
                escalation_level="URGENT",
                template_parameters={
                    "partner_name": "Site 01", "lot_id": "LTS-RECALL",
                    "cases": "8", "deadline": "2026-08-08T17:00:00Z",
                },
                rationale="Custody unconfirmed.", confidence=0.9,
            ),
        )
        return run_fleet(
            incident_id="INC-ALT", lot_id="LTS-RECALL", graph_result=graph,
            recovery_candidates=candidates, partner_state=partner_state,
            runner=scripted_runner(scripted),
        )

    ascending = run_with("CAND-LOT-ASC")
    largest_first = run_with("CAND-LOT-DEEPEST-FIRST")

    assert ascending["proposal"].status == "PROPOSED"
    assert largest_first["proposal"].status == "PROPOSED"
    # A different valid selection yields a materially different plan and hash.
    assert (ascending["recovery_candidate"]["allocations"]
            != largest_first["recovery_candidate"]["allocations"])
    assert (ascending["proposal"].proposal_hash
            != largest_first["proposal"].proposal_hash)
    # Both remain deterministically truthful.
    for result in (ascending, largest_first):
        candidate = result["recovery_candidate"]
        assert candidate["total_allocated_cases"] == 45
        assert candidate["total_shortfall_cases"] == 5


# --- Refusal paths ----------------------------------------------------------


@pytest.mark.parametrize("agent_id", [
    AGENT_NETWORK_CUSTODY, AGENT_FULFILLMENT_RECOVERY, AGENT_PARTNER_OPERATIONS,
])
def test_any_specialist_failure_requires_manual_review(agent_id):
    result = run_canonical(
        runner=scripted_runner(outputs(), fail=(agent_id, "ADK_MODEL_ERROR"))
    )
    assert result["proposal"].status == "MANUAL_REVIEW_REQUIRED"
    assert result["proposal"].reason_code == "ADK_MODEL_ERROR"
    assert result["recovery_candidate"] is None


def test_fabricated_custody_count_halts_before_the_planner_runs():
    calls = []
    fabricated = NetworkCustodyAssessment(
        lot_id="LTC-4471", total_cases_in_custody=114, confirmed_cases=88,
        unconfirmed_cases=8, unconfirmed_node_ids=["SITE-01"], max_path_depth=3,
        containment_assessment="UNCONFIRMED_DOWNSTREAM",
        narrative="Re-added an intermediate subtotal.",
    )
    result = run_canonical(
        runner=scripted_runner(outputs(custody=fabricated), calls=calls)
    )
    assert result["proposal"].status == "MANUAL_REVIEW_REQUIRED"
    assert result["proposal"].reason_code == "CUSTODY_TOTAL_MISMATCH"
    assert calls == [AGENT_NETWORK_CUSTODY]


def test_false_containment_claim_halts_the_fleet():
    false_claim = NetworkCustodyAssessment(
        lot_id="LTC-4471", total_cases_in_custody=96, confirmed_cases=88,
        unconfirmed_cases=8, unconfirmed_node_ids=["SITE-01"], max_path_depth=3,
        containment_assessment="FULLY_TRACED",
        narrative="Claims full containment despite unconfirmed cases.",
    )
    result = run_canonical(runner=scripted_runner(outputs(custody=false_claim)))
    assert result["proposal"].status == "MANUAL_REVIEW_REQUIRED"
    assert result["proposal"].reason_code == "CUSTODY_CONTAINMENT_MISMATCH"
    assert result["recovery_candidate"] is None


def test_invented_candidate_halts_before_partner_operations():
    calls = []
    result = run_canonical(
        runner=scripted_runner(
            outputs(candidate_id="CAND-INVENTED-BY-MODEL"), calls=calls
        )
    )
    assert result["proposal"].status == "MANUAL_REVIEW_REQUIRED"
    assert result["proposal"].reason_code == "UNKNOWN_RECOVERY_CANDIDATE"
    assert AGENT_PARTNER_OPERATIONS not in calls


def test_unapproved_partner_template_requires_manual_review():
    bad_partner = PartnerCommunication(
        partner_id="SITE-01", template_id="partner.freeform-outreach.v1",
        escalation_level="URGENT",
        template_parameters={"partner_name": "Site 01"},
        rationale="Wants to improvise.", confidence=0.9,
    )
    result = run_canonical(runner=scripted_runner(outputs(partner=bad_partner)))
    assert result["proposal"].status == "MANUAL_REVIEW_REQUIRED"
    assert result["proposal"].reason_code == "UNKNOWN_PARTNER_TEMPLATE"


def test_failed_proposal_records_the_failing_hop_for_audit():
    result = run_canonical(
        runner=scripted_runner(outputs(candidate_id="CAND-NOPE"))
    )
    trace = result["proposal"].delegation_trace
    assert trace[-1]["agent_id"] == AGENT_FULFILLMENT_RECOVERY
    assert trace[-1]["deterministic_validation"] == "UNKNOWN_RECOVERY_CANDIDATE"
