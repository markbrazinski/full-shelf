"""Finding 5: no ledger command may be attempted before the fleet is accepted.

The prior implementation committed five ledger commands before running the
fleet, then reported `ledger_mutation_attempted: false` on failure. These tests
inject a failure at every pre-mutation stage and assert that the ledger client
was never called, and that the returned counters are truthful.
"""

import importlib.util
import inspect
import os
from unittest.mock import patch

import pytest


main_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src", "main.py")
)
spec = importlib.util.spec_from_file_location("orchestrator_mutation_boundary", main_path)
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)


GRAPH = {
    "lot_id": "LOT-B1", "max_path_depth": 3, "unique_current_cases": 30,
    "confirmed_cases": 25, "unconfirmed_cases": 5,
    "unconfirmed_positions": [{
        "node_id": "SITE-9", "node_type": "SUBSITE", "name": "Site 9",
        "on_hand_cases": 5, "acknowledgment_status": "UNCONFIRMED", "path_depth": 3,
    }],
}
INPUTS = {
    "plan_id": "PLAN-B", "recalled_total_cases": 30,
    "safe_lots": [("SAFE-1", 10)],
    "affected_orders": [("O-1", "AG-1", 6), ("O-2", "AG-2", 9)],
}
APPROVED_SCREENING = {
    "status": "APPROVED", "safety_verdict": "PASSED",
    "managed_operation": "sanitizeUserPrompt", "correlation_id": "t" * 32,
}


def run(*, fleet_result=None, graph=GRAPH, inputs=INPUTS,
        screening=APPROVED_SCREENING, inputs_error=None,
        candidates_error=None, derive_error=None):
    """graph=None simulates an authoritative graph read failure.

    inputs_error raises that exception from the authoritative read instead.
    """
    """Run the managed recall path, recording every ledger command attempt."""
    attempts = []

    def execute(**kwargs):
        attempts.append(kwargs)
        status = "DENIED" if kwargs["command_type"] == "RECORD_REFUSAL" else "SUCCESS"
        return {
            "receipt": {"receipt_id": f"RCT-{len(attempts)}", "status": status,
                        "mutations_applied": 0 if status == "DENIED" else 1},
            "idempotent_replay": False,
        }

    fleet_patch = (
        patch.object(main, "_run_agent_fleet_proposal", return_value=fleet_result)
        if fleet_result is not None
        else patch.object(main, "_run_agent_fleet_proposal",
                          side_effect=AssertionError("fleet should not run"))
    )
    with (
        patch.object(main, "get_spanner_database", return_value=object()),
        patch.object(main, "inspect_recall_notice_with_model_armor",
                     return_value=screening),
        patch.object(main, "_persist_model_invocation_evidence"),
        patch.object(
            main, "_read_authoritative_recall_inputs",
            side_effect=(inputs_error if inputs_error
                         else lambda db, **kw: inputs),
        ),
        patch.object(
            main, "_run_managed_custody_graph",
            side_effect=(RuntimeError("graph unavailable") if graph is None
                         else lambda db, **kw: graph),
        ),
        patch.object(main, "execute_ledger_command", side_effect=execute),
        patch.object(main, "schedule_site01_deadline_task",
                     return_value={"task_name": "t"}),
        patch.object(
            main, "generate_recovery_candidates",
            side_effect=(candidates_error if candidates_error
                         else main.generate_recovery_candidates),
        ),
        patch.object(
            main, "_derive_safe_recovery",
            side_effect=(derive_error if derive_error
                         else main._derive_safe_recovery),
        ),
        fleet_patch,
    ):
        try:
            result = main._execute_managed_recall_event(
                tenant_id="east-bay-food-bank", coordinator_id="C",
                incident_id="INC-B", recalled_lot_id="LOT-B1",
                notice_text="Recall LOT-B1", source_event_id="ev",
                source_publish_time="2026-08-14T15:00:00Z",
                active_revision="rev08", trace_id="t" * 32,
            )
        except main.HTTPException as exc:
            result = {"http_error": exc.detail}
    return result, attempts


ACCEPTED = {
    "status": "ACCEPTED", "reason_code": None,
    "proposal": {"status": "PROPOSED", "proposal_hash": "h",
                 "delegation_trace": [], "partner": {"template_id": "x"},
                 "coordinator_session_id": "s", "coordination_run_id": "i"},
    "recovery_candidate": {
        "candidate_id": "CAND-LOT-ASC",
        "allocations": [{"allocation_id": "A", "agency_id": "AG-1",
                         "lot_id": "SAFE-1", "cases": 6},
                        {"allocation_id": "B", "agency_id": "AG-2",
                         "lot_id": "SAFE-1", "cases": 4}],
        "shortfalls": [{"shortfall_id": "S", "agency_id": "AG-2", "cases": 5}],
    },
    "extraction_evidence": {"lot_id": "LOT-B1", "product_name": "P",
                            "hazard": "H", "action_required": "A"},
}


@pytest.mark.parametrize("reason_code", [
    "ADK_MODEL_ERROR", "ADK_TIMEOUT", "COORDINATOR_TIMEOUT",
    "INVALID_STRUCTURED_OUTPUT", "UNKNOWN_RECOVERY_CANDIDATE",
    "CUSTODY_TOTAL_MISMATCH", "CUSTODY_CONTAINMENT_MISMATCH",
    "UNKNOWN_PARTNER_TEMPLATE", "PARTNER_ESCALATION_NOT_DETERMINISTIC",
    "SOURCE_ANCHOR_VALIDATION_FAILED", "INCOMPLETE_SPECIALIST_COVERAGE",
    "FLEET_EXECUTION_FAILED",
])
def test_every_fleet_failure_attempts_zero_ledger_commands(reason_code):
    result, attempts = run(fleet_result={
        "status": "MANUAL_REVIEW_REQUIRED", "reason_code": reason_code,
        "proposal": None, "recovery_candidate": None, "extraction_evidence": None,
    })
    assert result["hero_loop_status"] == "HALTED_FOR_MANUAL_REVIEW"
    assert result["manual_review_reason"] == reason_code
    assert attempts == [], "no ledger command may be attempted"
    assert result["ledger_commands_attempted"] == 0
    assert result["ledger_commands_accepted"] == 0
    assert result["mutations_committed"] == 0
    assert result["ledger_mutation_attempted"] is False


def test_model_armor_block_attempts_zero_ledger_commands():
    result, attempts = run(screening={
        "status": "BLOCKED", "safety_verdict": "FAILED_SAFETY_SCREENING",
        "correlation_id": "t" * 32,
    })
    assert result["hero_loop_status"] == "HALTED_BY_MODEL_ARMOR_SAFETY_MATCH"
    assert attempts == []
    assert result["ledger_mutation_attempted"] is False


def test_graph_mismatch_attempts_zero_ledger_commands():
    bad_graph = dict(GRAPH, unique_current_cases=999)
    result, attempts = run(graph=bad_graph)
    assert result["manual_review_reason"] == (
        "CUSTODY_TOTAL_DOES_NOT_MATCH_RECALLED_LOT"
    )
    assert result["halt_stage"] == "CUSTODY_RECONCILIATION"
    assert attempts == []
    assert result["ledger_commands_attempted"] == 0
    assert result["mutations_committed"] == 0


def test_every_pre_ledger_halt_reports_zero_counters():
    """Item 4: armor, read, graph, agent, tool, validation, timeout."""
    scenarios = [
        ("MODEL_ARMOR", dict(screening={
            "status": "BLOCKED", "safety_verdict": "FAILED_SAFETY_SCREENING",
            "correlation_id": "t" * 32})),
        ("AUTHORITATIVE_GRAPH_READ", dict(graph=None)),
        ("CUSTODY_RECONCILIATION",
         dict(graph=dict(GRAPH, unconfirmed_positions=[]))),
        ("AGENT_FLEET_PROPOSAL", dict(fleet_result={
            "status": "MANUAL_REVIEW_REQUIRED", "reason_code": "ADK_TIMEOUT",
            "proposal": None, "recovery_candidate": None,
            "extraction_evidence": None})),
    ]
    for label, kwargs in scenarios:
        result, attempts = run(**kwargs)
        assert attempts == [], label
        assert result["ledger_commands_attempted"] == 0, label
        assert result["ledger_commands_accepted"] == 0, label
        assert result["mutations_committed"] == 0, label
        assert result["ledger_mutation_attempted"] is False, label


def test_nonreconciling_candidate_attempts_zero_ledger_commands():
    bogus = dict(ACCEPTED)
    bogus["recovery_candidate"] = {
        "candidate_id": "CAND-BOGUS",
        "allocations": [{"allocation_id": "A", "agency_id": "AG-1",
                         "lot_id": "SAFE-1", "cases": 999}],
        "shortfalls": [{"shortfall_id": "S", "agency_id": "AG-2", "cases": 0}],
    }
    result, attempts = run(fleet_result=bogus)
    assert result["manual_review_reason"] == "FLEET_RECOVERY_DOES_NOT_RECONCILE"
    assert attempts == []
    assert result["ledger_commands_attempted"] == 0


def test_accepted_proposal_reports_truthful_command_counters():
    result, attempts = run(fleet_result=ACCEPTED)
    assert result["hero_loop_status"] == "COMPLETED"
    assert result["ledger_commands_attempted"] == len(attempts)
    assert result["ledger_commands_attempted"] == 8
    # RECORD_REFUSAL is denied by design, so accepted is one fewer.
    assert result["ledger_commands_accepted"] == 7
    assert result["mutations_committed"] == 7
    assert result["terminal_state"] == "PARTIALLY_CONTAINED"


def test_fleet_gate_precedes_every_ledger_command_in_source_order():
    source = inspect.getsource(main._execute_managed_recall_event)
    gate = source.index("PRE-MUTATION FLEET GATE")
    fleet = source.index("_run_agent_fleet_proposal(")
    mutation = source.index("MUTATION PHASE")
    first_command = source.index("open_result = _record(")
    assert gate < fleet < mutation < first_command


def test_no_ledger_command_helper_exists_before_the_mutation_phase():
    source = inspect.getsource(main._execute_managed_recall_event)
    mutation = source.index("MUTATION PHASE")
    assert "execute_ledger_command" not in source[:mutation]


def test_generic_authoritative_read_exception_fails_closed_with_zero_counters():
    """Item 4: a raw infrastructure error must not escape uncounted.

    A generic RuntimeError from the authoritative read previously propagated
    past the counter block entirely. It must now fail closed with zero ledger
    activity while keeping a retryable 503 classification.
    """
    result, attempts = run(inputs_error=RuntimeError("spanner unavailable"))
    assert result["hero_loop_status"] == "HALTED_FOR_MANUAL_REVIEW"
    assert result["halt_stage"] == "AUTHORITATIVE_READ"
    assert result["manual_review_reason"] == "AUTHORITATIVE_READ_UNAVAILABLE"
    assert result["http_status_classification"] == 503
    assert attempts == []
    assert result["ledger_commands_attempted"] == 0
    assert result["ledger_commands_accepted"] == 0
    assert result["mutations_committed"] == 0
    assert result["ledger_mutation_attempted"] is False
    # The raw error text must never reach evidence.
    assert "spanner unavailable" not in str(result)


def test_classified_read_failure_keeps_its_business_status():
    """A deterministic 409 stays a 409 while still reporting zero counters."""
    result, attempts = run(
        inputs_error=main.HTTPException(409, "RECOVERY_INPUTS_NOT_FOUND")
    )
    assert result["manual_review_reason"] == "RECOVERY_INPUTS_NOT_FOUND"
    assert result["http_status_classification"] == 409
    assert attempts == []
    assert result["ledger_commands_attempted"] == 0


# --- Item 2: candidate generation and cross-check are inside the gate --------


@pytest.mark.parametrize("error,reason,status", [
    (RuntimeError("unexpected planner defect"),
     "RECOVERY_CANDIDATE_GENERATION_FAILED", 500),
    (main.HTTPException(409, "PARTIAL_RECOVERY_POLICY_INPUTS_REQUIRED"),
     "PARTIAL_RECOVERY_POLICY_INPUTS_REQUIRED", 409),
])
def test_candidate_generation_failure_returns_zero_mutation_evidence(
    error, reason, status
):
    result, attempts = run(candidates_error=error)
    assert result["hero_loop_status"] == "HALTED_FOR_MANUAL_REVIEW"
    assert result["halt_stage"] == "RECOVERY_CANDIDATE_GENERATION"
    assert result["manual_review_reason"] == reason
    assert result["http_status_classification"] == status
    assert attempts == []
    assert result["ledger_commands_attempted"] == 0
    assert result["ledger_commands_accepted"] == 0
    assert result["mutations_committed"] == 0
    assert result["ledger_mutation_attempted"] is False
    assert "unexpected planner defect" not in str(result)


@pytest.mark.parametrize("error,reason,status", [
    (RuntimeError("cross-check exploded"), "RECOVERY_CROSS_CHECK_FAILED", 500),
    (main.HTTPException(409, "PARTIAL_RECOVERY_POLICY_INPUTS_REQUIRED"),
     "PARTIAL_RECOVERY_POLICY_INPUTS_REQUIRED", 409),
])
def test_recovery_cross_check_failure_returns_zero_mutation_evidence(
    error, reason, status
):
    result, attempts = run(fleet_result=ACCEPTED, derive_error=error)
    assert result["hero_loop_status"] == "HALTED_FOR_MANUAL_REVIEW"
    assert result["halt_stage"] == "FLEET_RECOVERY_RECONCILIATION"
    assert result["manual_review_reason"] == reason
    assert result["http_status_classification"] == status
    assert attempts == []
    assert result["ledger_commands_attempted"] == 0
    assert result["mutations_committed"] == 0
    assert "cross-check exploded" not in str(result)


@pytest.mark.parametrize("control", [KeyboardInterrupt, SystemExit])
def test_process_control_exceptions_are_not_swallowed(control):
    """Cancellation and process control must propagate, never become a halt."""
    with pytest.raises(control):
        run(candidates_error=control())


def test_cancellation_is_not_swallowed():
    import asyncio

    with pytest.raises(asyncio.CancelledError):
        run(candidates_error=asyncio.CancelledError())
