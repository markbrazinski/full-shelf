"""Orchestrator-level proof that the fleet is advisory only.

The fleet sits between graph reconciliation and safe-stock allocation. These
tests prove that an advisory failure halts before any recovery mutation, that a
model-selected candidate must still reconcile with the accepted deterministic
policy, and that ledger submission stays outside the ADK fleet entirely.
"""

import importlib.util
import inspect
import os
from unittest.mock import patch

import pytest


main_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src", "main.py")
)
spec = importlib.util.spec_from_file_location("orchestrator_fleet_integration", main_path)
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)


EXTRACTION = {
    "status": "EXTRACTION_VALIDATED", "lot_id": "LOT-FLEET-1", "downstream_allowed": True,
    "product_name": "Spinach", "hazard": "Listeria", "action_required": "PAUSE",
    "adk_session_id": "s", "adk_run_id": "r", "adk_event_id": "e",
}
GRAPH = {
    "lot_id": "LOT-FLEET-1", "max_path_depth": 3,
    "unique_current_cases": 30, "confirmed_cases": 25, "unconfirmed_cases": 5,
    "unconfirmed_positions": [{
        "node_id": "SITE-9", "node_type": "SUBSITE", "name": "Site 9",
        "on_hand_cases": 5, "acknowledgment_status": "UNCONFIRMED", "path_depth": 3,
    }],
}
INPUTS = {
    "plan_id": "PLAN-F", "recalled_total_cases": 30,
    "safe_lots": [("SAFE-1", 10)],
    "affected_orders": [("O-1", "AG-1", 6), ("O-2", "AG-2", 9)],
}


def run_hero(commands, *, fleet_result):
    def execute(**kwargs):
        commands.append(kwargs)
        status = "DENIED" if kwargs["command_type"] == "RECORD_REFUSAL" else "SUCCESS"
        return {
            "receipt": {"receipt_id": f"RCT-{len(commands)}", "status": status,
                        "mutations_applied": 0 if status == "DENIED" else 1},
            "idempotent_replay": False,
        }

    with (
        patch.object(main, "get_spanner_database", return_value=object()),
        patch.object(main, "inspect_recall_notice_with_model_armor", return_value={
            "status": "APPROVED", "safety_verdict": "PASSED",
            "managed_operation": "sanitizeUserPrompt", "correlation_id": "t" * 32,
        }),
        patch.object(main, "extract_recall_entities_with_gemini_35", return_value=EXTRACTION),
        patch.object(main, "_persist_model_invocation_evidence"),
        patch.object(main, "_read_authoritative_recall_inputs", return_value=INPUTS),
        patch.object(main, "_run_managed_custody_graph", return_value=GRAPH),
        patch.object(main, "execute_ledger_command", side_effect=execute),
        patch.object(main, "schedule_site01_deadline_task", return_value={"task_name": "t"}),
        patch.object(main, "_run_agent_fleet_proposal", return_value=fleet_result),
    ):
        return main._execute_managed_recall_event(
            tenant_id="east-bay-food-bank", coordinator_id="C", incident_id="INC-F",
            recalled_lot_id="LOT-FLEET-1", notice_text="Recall LOT-FLEET-1",
            source_event_id="ev", source_publish_time="2026-08-14T15:00:00Z",
            active_revision="rev08", trace_id="t" * 32,
        )


@pytest.mark.parametrize("reason_code", [
    "ADK_MODEL_ERROR", "INVALID_STRUCTURED_OUTPUT", "UNKNOWN_RECOVERY_CANDIDATE",
    "CUSTODY_TOTAL_MISMATCH", "UNKNOWN_PARTNER_TEMPLATE", "ADK_TIMEOUT",
    "FLEET_EXECUTION_FAILED",
])
def test_fleet_failure_halts_before_any_recovery_mutation(reason_code):
    commands = []
    result = run_hero(commands, fleet_result={
        "status": "MANUAL_REVIEW_REQUIRED", "reason_code": reason_code,
        "proposal": None, "recovery_candidate": None,
        "extraction_evidence": None,
    })
    assert result["hero_loop_status"] == "HALTED_FOR_MANUAL_REVIEW"
    assert result["halt_stage"] == "AGENT_FLEET_PROPOSAL"
    assert result["manual_review_reason"] == reason_code
    # The fleet gate precedes every ledger command, so nothing is attempted.
    assert commands == []
    assert result["ledger_commands_attempted"] == 0
    assert result["mutations_committed"] == 0


def test_fleet_candidate_that_contradicts_policy_totals_is_rejected():
    # A candidate whose totals do not reconcile with the accepted deterministic
    # policy must never reach the ledger. The check now runs inside the
    # pre-mutation gate, so it halts with zero ledger commands attempted.
    commands = []
    result = run_hero(commands, fleet_result={
        "status": "ACCEPTED", "reason_code": None,
        "proposal": {"status": "PROPOSED", "proposal_hash": "h",
                     "delegation_trace": [], "partner": {"template_id": "x"},
                     "coordinator_session_id": "s",
                     "coordination_run_id": "i"},
        "recovery_candidate": {
            "candidate_id": "CAND-BOGUS",
            "allocations": [{"agency_id": "AG-1", "lot_id": "SAFE-1", "cases": 999}],
            "shortfalls": [{"agency_id": "AG-2", "cases": 0}],
        },
        "extraction_evidence": {"lot_id": "LOT-FLEET-1"},
    })
    assert result["manual_review_reason"] == "FLEET_RECOVERY_DOES_NOT_RECONCILE"
    assert commands == []
    assert result["ledger_commands_attempted"] == 0


def test_ledger_submission_lives_outside_the_adk_fleet():
    from full_shelf_domain.fleet import agents, contracts, coordinator, tools, validation

    for module in (agents, contracts, coordinator, tools, validation):
        source = inspect.getsource(module)
        for forbidden in ("execute_ledger_command", "post_to_plan_ledger",
                          "PLAN_LEDGER_URL", "ALLOCATE_SAFE_STOCK",
                          "SET_INCIDENT_STATUS"):
            assert forbidden not in source, f"{module.__name__} references {forbidden}"


def test_orchestrator_submits_only_after_deterministic_reconciliation():
    source = inspect.getsource(main._execute_managed_recall_event)
    reconcile = source.index("FLEET_RECOVERY_DOES_NOT_RECONCILE")
    first_command = source.index("open_result = _record(")
    allocate = source.index('"safe-recovery", "ALLOCATE_SAFE_STOCK"')
    assert reconcile < first_command < allocate
