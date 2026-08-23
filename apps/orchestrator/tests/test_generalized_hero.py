import importlib.util
import os
from unittest.mock import patch


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


def altered_fleet_runner(agent_id_to_output):
    """Replay scripted specialist outputs through the real fleet sequence."""

    def _runner(*, agent, agent_id, prompt, output_model, timeout_seconds=None):
        return {
            "output": agent_id_to_output[agent_id],
            "execution": {
                "agent_id": agent_id, "agent_name": agent.name,
                "model_used": "gemini-3.5-flash",
                "adk_framework": "google-adk/test",
                "adk_session_id": f"session-{agent_id}",
                "adk_run_id": f"run-{agent_id}",
                "adk_event_id": f"event-{agent_id}",
                "declared_tools": [], "tool_invocations": [],
            },
        }

    return _runner


def altered_specialist_outputs():
    from full_shelf_domain.fleet.contracts import (
        AGENT_FULFILLMENT_RECOVERY, AGENT_NETWORK_CUSTODY,
        AGENT_PARTNER_OPERATIONS, NetworkCustodyAssessment,
        PartnerCommunication, RecoverySelection,
    )

    return {
        AGENT_NETWORK_CUSTODY: NetworkCustodyAssessment(
            lot_id="LOT-ALTERED-9001", total_cases_in_custody=51,
            confirmed_cases=46, unconfirmed_cases=5,
            unconfirmed_node_ids=["SITE-ALTERED-77"], max_path_depth=4,
            containment_assessment="UNCONFIRMED_DOWNSTREAM",
            narrative="Five cases at Site 77 remain unconfirmed.",
        ),
        AGENT_FULFILLMENT_RECOVERY: RecoverySelection(
            selected_candidate_id="CAND-LOT-ASC",
            rationale="Only feasible allocation of the available safe stock.",
            cited_constraints=["21 safe cases available"],
            tradeoffs="Two agencies retain truthful shortfalls.",
            confidence=0.88,
        ),
        AGENT_PARTNER_OPERATIONS: PartnerCommunication(
            partner_id="SITE-ALTERED-77",
            template_id="partner.acknowledgment-request.v1",
            escalation_level="PRIORITY",
            template_parameters={
                "partner_name": "Site 77", "lot_id": "LOT-ALTERED-9001",
                "cases": "5", "deadline": "",
            },
            rationale="Custody is unconfirmed.", confidence=0.8,
        ),
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
        "status": "EXTRACTION_VALIDATED", "lot_id": "LOT-ALTERED-9001",
        "product_name": "Baby spinach", "hazard": "Listeria monocytogenes",
        "action_required": "PAUSE_DISTRIBUTION", "downstream_allowed": True,
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
        patch.object(main, "extract_recall_entities_with_gemini_35", return_value=extraction),
        patch.object(main, "_persist_model_invocation_evidence"),
        patch.object(main, "_read_authoritative_recall_inputs", return_value=inputs),
        patch.object(main, "_run_managed_custody_graph", return_value=graph),
        patch.object(main, "execute_ledger_command", side_effect=execute),
        patch.object(main, "schedule_site01_deadline_task", return_value=task) as schedule,
        patch.object(
            main, "run_fleet",
            side_effect=lambda **kw: __import__(
                "full_shelf_domain.fleet.coordinator", fromlist=["run_fleet"]
            ).run_fleet(
                **{**kw, "runner": altered_fleet_runner(altered_specialist_outputs())}
            ),
        ),
    ):
        result = main._execute_managed_recall_event(
            tenant_id="east-bay-food-bank", coordinator_id="COORD-ALTERED",
            incident_id="INC-ALTERED", recalled_lot_id="LOT-ALTERED-9001",
            notice_text="Recall LOT-ALTERED-9001 Baby spinach Listeria monocytogenes",
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
    assert fleet["proposal_status"] == "PROPOSED"
    assert fleet["deterministic_reconciliation"] == "RECONCILED_WITH_ACCEPTED_POLICY"
    assert [entry["agent_id"] for entry in fleet["delegation_trace"]] == [
        "full-shelf.recall-extraction.v1",
        "full-shelf.network-custody.v1",
        "full-shelf.fulfillment-recovery.v1",
        "full-shelf.partner-operations.v1",
    ]
    assert fleet["selected_candidate_id"] in fleet["candidate_ids_offered"]
