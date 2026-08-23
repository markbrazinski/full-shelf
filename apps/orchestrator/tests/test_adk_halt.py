import importlib.util
import os


main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("orchestrator_adk_main", main_path)
orchestrator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrator)


def approved_screening(correlation_id):
    return {
        "status": "APPROVED",
        "safety_verdict": "PASSED",
        "managed_operation": "sanitizeUserPrompt",
        "correlation_id": correlation_id,
    }


def failed_extraction(correlation_id):
    return {
        "status": "MANUAL_REVIEW_REQUIRED",
        "reason_code": "INVALID_STRUCTURED_OUTPUT",
        "model_used": "gemini-3.5-flash",
        "adk_session_id": "session-failed",
        "adk_run_id": "run-failed",
        "correlation_id": correlation_id,
        "validation_status": "MANUAL_REVIEW_REQUIRED",
        "downstream_allowed": False,
    }


def successful_extraction(correlation_id):
    return {
        "status": "EXTRACTION_VALIDATED",
        "lot_id": "ALT-8842",
        "product_name": "Green Beans",
        "hazard": "Listeria monocytogenes",
        "action_required": "PAUSE_DISTRIBUTION",
        "source_anchor": "Supplier Safety Bulletin SB-8842",
        "model_used": "gemini-3.5-flash",
        "vertex_location": "global",
        "adk_framework": "google-adk/2.6.1",
        "adk_session_backend": "InMemorySessionService",
        "adk_session_id": "session-success",
        "adk_run_id": "run-success",
        "adk_event_id": "event-success",
        "correlation_id": correlation_id,
        "validation_status": "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED",
        "downstream_allowed": True,
    }


def test_hero_loop_model_failure_halts_before_ledger(monkeypatch):
    """Model failure halts with zero ledger calls.

    Extraction now runs inside the Incident Coordinator's ADK execution rather
    than standalone, so the failure is injected at the fleet boundary. The
    guarantee under test is unchanged and is now stronger: the ledger client is
    never called at all, not merely stopped partway through.
    """
    monkeypatch.setattr(orchestrator, "get_spanner_database", lambda database_id=None: object())
    monkeypatch.setattr(
        orchestrator,
        "inspect_recall_notice_with_model_armor",
        lambda text, correlation_id: approved_screening(correlation_id),
    )
    monkeypatch.setattr(
        orchestrator, "_read_authoritative_recall_inputs",
        lambda db, **kwargs: {
            "plan_id": "PLAN-X", "recalled_total_cases": 51,
            "safe_lots": [("SAFE-1", 10)],
            "affected_orders": [("O-1", "AG-1", 6), ("O-2", "AG-2", 9)],
        },
    )
    monkeypatch.setattr(
        orchestrator, "_run_managed_custody_graph",
        lambda db, **kwargs: {
            "lot_id": "ALT-8842", "max_path_depth": 3,
            "unique_current_cases": 51, "confirmed_cases": 46,
            "unconfirmed_cases": 5,
            "unconfirmed_positions": [{
                "node_id": "SITE-X", "node_type": "SUBSITE", "name": "Site X",
                "on_hand_cases": 5, "acknowledgment_status": "UNCONFIRMED",
                "path_depth": 3,
            }],
        },
    )
    monkeypatch.setattr(
        orchestrator, "_run_agent_fleet_proposal",
        lambda **kwargs: {
            "status": "MANUAL_REVIEW_REQUIRED",
            "reason_code": "INVALID_STRUCTURED_OUTPUT",
            "proposal": None, "recovery_candidate": None,
            "extraction_evidence": None,
        },
    )
    monkeypatch.setattr(orchestrator, "_persist_model_invocation_evidence", lambda *a, **k: None)
    monkeypatch.setattr(
        orchestrator,
        "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("ledger called after ADK failure")),
    )

    result = orchestrator._execute_managed_recall_event(
        tenant_id="east-bay-food-bank", coordinator_id="COORD-X",
        incident_id="INC-X", recalled_lot_id="ALT-8842", notice_text="notice",
        source_event_id="message-x", source_publish_time="2026-08-14T00:00:00Z",
        active_revision="rev08", trace_id="corr-hero-fail",
    )
    assert result["hero_loop_status"] == "HALTED_FOR_MANUAL_REVIEW"
    assert result["manual_review_reason"] == "INVALID_STRUCTURED_OUTPUT"
    assert result["ledger_commands_attempted"] == 0
    assert result["mutations_committed"] == 0
    assert result["ledger_mutation_attempted"] is False


def test_extraction_preflight_success_persists_ids_without_ledger(monkeypatch):
    monkeypatch.setattr(orchestrator, "_verify_internal_workload", lambda value: None)
    monkeypatch.setattr(orchestrator, "generate_trace_id", lambda: "corr-preflight-success")
    monkeypatch.setattr(
        orchestrator,
        "inspect_recall_notice_with_model_armor",
        lambda text, correlation_id: approved_screening(correlation_id),
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_recall_entities_with_gemini_35",
        lambda text, correlation_id: successful_extraction(correlation_id),
    )
    monkeypatch.setattr(
        orchestrator,
        "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("ledger called by preflight")),
    )

    result = orchestrator.extraction_preflight(
        orchestrator.RecallArmorPreflightRequest(
            notice_text="Supplier Safety Bulletin SB-8842"
        ),
    )
    assert result["preflight_status"] == "READY_FOR_POLICY_REVIEW"
    assert result["model_invocation_record"]["adk_session_id"] == "session-success"
    assert result["model_invocation_record"]["adk_run_id"] == "run-success"
    assert result["identifiers_persisted_to"] == "CLOUD_LOGGING"
    assert result["ledger_mutation_attempted"] is False


def test_extraction_preflight_failure_stops_at_manual_review(monkeypatch):
    monkeypatch.setattr(orchestrator, "_verify_internal_workload", lambda value: None)
    monkeypatch.setattr(orchestrator, "generate_trace_id", lambda: "corr-preflight-fail")
    monkeypatch.setattr(
        orchestrator,
        "inspect_recall_notice_with_model_armor",
        lambda text, correlation_id: approved_screening(correlation_id),
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_recall_entities_with_gemini_35",
        lambda text, correlation_id: failed_extraction(correlation_id),
    )
    monkeypatch.setattr(
        orchestrator,
        "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("ledger called after failure")),
    )

    result = orchestrator.extraction_preflight(
        orchestrator.RecallArmorPreflightRequest(notice_text="invalid model response"),
    )
    assert result["preflight_status"] == "MANUAL_REVIEW_REQUIRED"
    assert result["next_authorized_stage"] is None
    assert result["ledger_mutation_attempted"] is False
