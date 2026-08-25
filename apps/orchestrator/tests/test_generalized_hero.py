import importlib.util
import os
import pathlib
import sys
from unittest.mock import patch

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[3] / "packages/domain/tests")
)
from fleet_fakes import scripted_gemini  # noqa: E402


main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("orchestrator_generalized_hero", main_path)
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)


def test_altered_recovery_is_derived_from_authoritative_orders_and_safe_stock():
    allocations, shortfalls = main._derive_safe_recovery(
        incident_id="INC-ALTERED",
        safe_lots=[("SAFE-99", 21)],
        affected_orders=[
            ("ORDER-X", "AGENCY-77", 9),
            ("ORDER-Y", "AGENCY-88", 17),
            ("ORDER-Z", "AGENCY-99", 8),
        ],
    )

    assert [(row["agency_id"], row["cases"]) for row in allocations] == [
        ("AGENCY-77", 9), ("AGENCY-88", 12)
    ]
    assert [(row["agency_id"], row["cases"]) for row in shortfalls] == [
        ("AGENCY-88", 5), ("AGENCY-99", 8)
    ]
    assert all("ALT" not in row["allocation_id"] for row in allocations)


ALTERED_NOTICE = (
    "Recall Lot LOT-ALTERED-9001 Baby spinach Listeria monocytogenes "
    "PAUSE_DISTRIBUTION"
)

ALTERED_REPLIES = {
    "IncidentLeadAgent": {
        "incident_class": "FOOD_SAFETY_RECALL",
        "source_event_id": "pubsub-altered",
        "affected_capabilities": ["cold_chain", "fulfillment"],
        "affected_commitment_ids": ["ORDER-X", "ORDER-Y"],
        "selected_playbook_id": "recall-response-playbook-v1",
        "required_specialists": [
            "full-shelf.recall-intake-extraction.v2",
            "full-shelf.network-custody.v2",
            "full-shelf.fulfillment-planning-recovery.v2",
        ],
        "immediate_safety_actions": ["pause_distribution", "notify_sites"],
        "rationale": "Food safety recall scope determined from notice.",
        "confidence": 0.95,
    },
    # V2 per-field source anchors: every value must be contained by its own
    # quote, and every quote must be a literal substring of ALTERED_NOTICE.
    "RecallIntakeExtractionAgent": {
        "source_event_id": "pubsub-altered",
        "lot_id": {"value": "LOT-ALTERED-9001", "quote": "Lot LOT-ALTERED-9001"},
        "hazard": {"value": "Listeria monocytogenes",
                   "quote": "Listeria monocytogenes"},
        "notice_scope": [{"value": "Baby spinach", "quote": "Baby spinach"}],
        "notice_time": None,
        "missing_required_fields": [],
    },
    "NetworkAndCustodyAgent": {
        "lot_id": "LOT-ALTERED-9001", "total_cases_in_custody": 51,
        "confirmed_cases": 46, "unconfirmed_cases": 5,
        "unconfirmed_node_ids": ["SITE-ALTERED-77"], "max_path_depth": 4,
        "containment_assessment": "UNCONFIRMED_DOWNSTREAM",
        "narrative": "Five cases at Site 77 remain unconfirmed.",
    },
    "FulfillmentPlanningRecoveryAgent": {
        "selected_candidate_id": "CAND-LOT-ASC",
        # operating_objective is required in V2: the agent must name which
        # objective it selected under, so a recall recovery cannot be mistaken
        # for ordinary daily planning.
        "operating_objective": "RECALL_RECOVERY",
        "rationale": "Only feasible allocation of the available safe stock.",
        "cited_constraints": ["21 safe cases available"],
        "tradeoffs": "Two agencies retain truthful shortfalls.",
        "confidence": 0.88,
    },
    "PartnerOperationsAgent": {
        "partner_id": "SITE-ALTERED-77",
        "template_id": "partner.shortfall-notice.v1",
        "escalation_level": "PRIORITY",
        "template_parameters": {"partner_name": "Site 77",
                                "lot_id": "LOT-ALTERED-9001", "cases": "5"},
        "rationale": "Custody is unconfirmed with no deadline.", "confidence": 0.8,
    },
}


def test_same_managed_hero_uses_altered_ids_quantities_and_calculated_outcome():
    commands = []

    def execute(**kwargs):
        commands.append(kwargs)
        status = "DENIED" if kwargs["command_type"] == "RECORD_REFUSAL" else "SUCCESS"
        return {
            "receipt": {
                "receipt_id": f"RCT-{len(commands)}",
                "status": status,
                "mutations_applied": 0 if status == "DENIED" else 1,
            },
            "idempotent_replay": False,
        }

    extraction = {
        "status": "EXTRACTION_VALIDATED",
        "lot_id": {"value": "LOT-ALTERED-9001", "quote": "Lot LOT-ALTERED-9001"},
        "hazard": {"value": "Listeria monocytogenes",
                   "quote": "Listeria monocytogenes"},
        "notice_scope": [{"value": "Baby spinach", "quote": "Baby spinach"}],
        "downstream_allowed": True,
        "adk_session_id": "session-alt", "adk_run_id": "run-alt",
        "adk_event_id": "event-alt", "correlation_id": "trace-alt",
    }
    graph = {
        "lot_id": "LOT-ALTERED-9001", "max_path_depth": 4,
        "unique_current_cases": 51, "confirmed_cases": 46, "unconfirmed_cases": 5,
        "unconfirmed_positions": [{
            "node_id": "SITE-ALTERED-77", "node_type": "DOWNSTREAM_SITE",
            "name": "Site 77", "on_hand_cases": 5,
            "acknowledgment_status": "UNCONFIRMED", "path_depth": 4,
        }],
    }
    inputs = {
        "plan_id": "PLAN-ALTERED", "recalled_total_cases": 51,
        "safe_lots": [("SAFE-ALTERED-99", 21)],
        "affected_orders": [
            ("ORDER-X", "AGENCY-77", 9),
            ("ORDER-Y", "AGENCY-88", 17),
            ("ORDER-Z", "AGENCY-99", 8),
        ],
    }
    task = {"task_name": "projects/p/locations/l/queues/q/tasks/ack-alt"}
    with (
        patch.object(main, "get_spanner_database", return_value=object()),
        patch.object(main, "inspect_recall_notice_with_model_armor", return_value={
            "status": "APPROVED", "safety_verdict": "PASSED",
            "managed_operation": "sanitizeUserPrompt",
            "correlation_id": "0123456789abcdef0123456789abcdef",
        }),
        patch.object(main, "_persist_model_invocation_evidence"),
        patch.object(main, "_read_authoritative_recall_inputs", return_value=inputs),
        patch.object(main, "_run_managed_custody_graph", return_value=graph),
        patch.object(main, "execute_ledger_command", side_effect=execute),
        patch.object(main, "schedule_site01_deadline_task", return_value=task) as schedule,
        scripted_gemini(overrides=ALTERED_REPLIES),
    ):
        result = main._execute_managed_recall_event(
            tenant_id="east-bay-food-bank", coordinator_id="COORD-ALTERED",
            incident_id="INC-ALTERED", recalled_lot_id="LOT-ALTERED-9001",
            notice_text=ALTERED_NOTICE,
            source_event_id="pubsub-altered", source_publish_time="2026-08-14T15:00:00Z",
            active_revision="rev08", trace_id="0123456789abcdef0123456789abcdef",
        )

    assert result["hero_loop_status"] == "COMPLETED"
    assert result["terminal_state"] == "PARTIALLY_CONTAINED"
    assert result["safe_stock_recovery"]["shortfalls"][0]["cases"] == 5
    invalidation = next(row for row in commands if row["command_type"] == "INVALIDATE_PLAN")
    assert invalidation["payload"]["plan_id"] == "PLAN-ALTERED"
    recovery = next(row for row in commands if row["command_type"] == "ALLOCATE_SAFE_STOCK")
    assert {row["agency_id"] for row in recovery["payload"]["shortfalls"]} == {
        "AGENCY-88", "AGENCY-99"
    }
    refusal = next(row for row in commands if row["command_type"] == "RECORD_REFUSAL")
    assert refusal["payload"]["subject_id"] == "SITE-ALTERED-77"
    assert refusal["payload"]["affected_cases"] == 5
    assert schedule.call_args.kwargs["coordinator_id"] == "COORD-ALTERED"
    assert schedule.call_args.kwargs["site_id"] == "SITE-ALTERED-77"
    opened = next(row for row in commands if row["command_type"] == "OPEN_RECALL_INCIDENT")
    assert opened["payload"]["model_armor_correlation_id"] == (
        "0123456789abcdef0123456789abcdef"
    )

    # The fleet delegated on the altered scenario and its selection reconciled
    # with the deterministic recovery policy rather than any canonical memory.
    fleet = result["agent_fleet"]
    assert fleet["root_agent_id"] == "full-shelf.incident-coordinator.v1"
    assert fleet["coordination_run_id"]
    assert fleet["coordinator_session_id"]
    # Each specialist reports its own distinct ADK session, never the
    # coordinator's, and no entry claims ADK parentage.
    sessions = {e["specialist_session_id"] for e in fleet["delegation_trace"]}
    assert len(sessions) == 4  # §6 recall path: Extraction, Lead, Custody, Fulfillment
    assert fleet["coordinator_session_id"] not in sessions
    synthetic_field = "_".join(["parent", "agent", "id"])
    assert all(synthetic_field not in e for e in fleet["delegation_trace"])
    assert fleet["proposal_status"] == "PROPOSED"
    assert [entry["agent_id"] for entry in fleet["delegation_trace"]] == [
        "full-shelf.recall-intake-extraction.v2",
        "full-shelf.incident-lead.v1",
        "full-shelf.network-custody.v2",
        "full-shelf.fulfillment-planning-recovery.v2",
    ]
    assert fleet["selected_candidate_id"] in fleet["candidate_ids_offered"]
