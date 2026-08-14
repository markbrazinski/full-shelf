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
        "adk_framework": "google-adk/2.6.3",
        "adk_session_backend": "InMemorySessionService",
        "adk_session_id": "session-success",
        "adk_run_id": "run-success",
        "adk_event_id": "event-success",
        "correlation_id": correlation_id,
        "validation_status": "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED",
        "downstream_allowed": True,
    }


def test_hero_loop_model_failure_halts_before_ledger(monkeypatch):
    monkeypatch.setattr(orchestrator, "verify_judge_key", lambda value: None)
    monkeypatch.setattr(orchestrator, "generate_trace_id", lambda: "corr-hero-fail")
    monkeypatch.setattr(orchestrator, "get_spanner_database", lambda database_id=None: object())
    monkeypatch.setattr(
        orchestrator,
        "inspect_recall_notice_with_model_armor",
        lambda text: approved_screening("armor-corr"),
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_recall_entities_with_gemini_35",
        lambda text, correlation_id: failed_extraction(correlation_id),
    )
    monkeypatch.setattr(
        orchestrator,
        "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("ledger called after ADK failure")),
    )

    result = orchestrator.execute_hero_loop(x_api_key="test")
    assert result["hero_loop_status"] == "HALTED_FOR_MANUAL_REVIEW"
    assert result["gemini_extraction"]["downstream_allowed"] is False


def test_extraction_preflight_success_persists_ids_without_ledger(monkeypatch):
    monkeypatch.setattr(orchestrator, "verify_judge_key", lambda value: None)
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
        x_api_key="test",
    )
    assert result["preflight_status"] == "READY_FOR_POLICY_REVIEW"
    assert result["model_invocation_record"]["adk_session_id"] == "session-success"
    assert result["model_invocation_record"]["adk_run_id"] == "run-success"
    assert result["identifiers_persisted_to"] == "CLOUD_LOGGING"
    assert result["ledger_mutation_attempted"] is False


def test_extraction_preflight_failure_stops_at_manual_review(monkeypatch):
    monkeypatch.setattr(orchestrator, "verify_judge_key", lambda value: None)
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
        x_api_key="test",
    )
    assert result["preflight_status"] == "MANUAL_REVIEW_REQUIRED"
    assert result["next_authorized_stage"] is None
    assert result["ledger_mutation_attempted"] is False
