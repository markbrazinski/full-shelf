import importlib.util
import os


main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("orchestrator_model_armor_main", main_path)
orchestrator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrator)


def test_model_armor_failure_halts_before_gemini_or_mutation(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_spanner_database", lambda database_id=None: object())
    monkeypatch.setattr(orchestrator, "inspect_recall_notice_with_model_armor", lambda text, correlation_id: {
        "status": "SERVICE_UNAVAILABLE", "safety_verdict": "BLOCKED_API_FAILURE",
        "managed_operation": "sanitizeUserPrompt",
    })
    monkeypatch.setattr(
        orchestrator, "extract_recall_entities_with_gemini_35",
        lambda text, correlation_id: (_ for _ in ()).throw(AssertionError("Gemini called after Armor failure")),
    )
    monkeypatch.setattr(
        orchestrator, "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("mutation called after Armor failure")),
    )
    result = orchestrator._execute_managed_recall_event(
        tenant_id="east-bay-food-bank", coordinator_id="COORD-X",
        incident_id="INC-X", recalled_lot_id="LOT-X", notice_text="notice",
        source_event_id="message-x", source_publish_time="2026-08-14T00:00:00Z",
        active_revision="rev08", trace_id="0123456789abcdef0123456789abcdef",
    )
    assert result["hero_loop_status"] == "HALTED_BY_MODEL_ARMOR_SERVICE_FAILURE"


def test_model_armor_match_halts_before_gemini_or_mutation(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_spanner_database", lambda database_id=None: object())
    monkeypatch.setattr(orchestrator, "inspect_recall_notice_with_model_armor", lambda text, correlation_id: {
        "status": "BLOCKED", "safety_verdict": "FAILED_SAFETY_SCREENING",
        "managed_operation": "sanitizeUserPrompt",
    })
    monkeypatch.setattr(
        orchestrator, "extract_recall_entities_with_gemini_35",
        lambda text, correlation_id: (_ for _ in ()).throw(AssertionError("Gemini called after Armor match")),
    )
    monkeypatch.setattr(
        orchestrator, "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("mutation called after Armor match")),
    )
    result = orchestrator._execute_managed_recall_event(
        tenant_id="east-bay-food-bank", coordinator_id="COORD-X",
        incident_id="INC-X", recalled_lot_id="LOT-X", notice_text="notice",
        source_event_id="message-x", source_publish_time="2026-08-14T00:00:00Z",
        active_revision="rev08", trace_id="0123456789abcdef0123456789abcdef",
    )
    assert result["hero_loop_status"] == "HALTED_BY_MODEL_ARMOR_SAFETY_MATCH"


def test_approved_screening_without_correlation_halts_before_downstream(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_spanner_database", lambda database_id=None: object())
    monkeypatch.setattr(orchestrator, "inspect_recall_notice_with_model_armor", lambda text, correlation_id: {
        "status": "APPROVED", "safety_verdict": "PASSED",
        "managed_operation": "sanitizeUserPrompt",
    })
    monkeypatch.setattr(
        orchestrator, "extract_recall_entities_with_gemini_35",
        lambda text, correlation_id: (_ for _ in ()).throw(AssertionError("Gemini called without managed correlation")),
    )
    monkeypatch.setattr(
        orchestrator, "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("mutation called without managed correlation")),
    )

    result = orchestrator._execute_managed_recall_event(
        tenant_id="east-bay-food-bank", coordinator_id="COORD-X",
        incident_id="INC-X", recalled_lot_id="LOT-X", notice_text="notice",
        source_event_id="message-x", source_publish_time="2026-08-14T00:00:00Z",
        active_revision="rev08", trace_id="0123456789abcdef0123456789abcdef",
    )

    assert result["hero_loop_status"] == "HALTED_BY_MODEL_ARMOR_SERVICE_FAILURE"
    assert result["ledger_mutation_attempted"] is False


def test_approved_screening_with_substituted_correlation_halts_before_downstream(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_spanner_database", lambda database_id=None: object())
    monkeypatch.setattr(orchestrator, "inspect_recall_notice_with_model_armor", lambda text, correlation_id: {
        "status": "APPROVED", "safety_verdict": "PASSED",
        "managed_operation": "sanitizeUserPrompt",
        "correlation_id": "abcdef0123456789abcdef0123456789",
    })
    monkeypatch.setattr(
        orchestrator, "extract_recall_entities_with_gemini_35",
        lambda text, correlation_id: (_ for _ in ()).throw(AssertionError("Gemini called with substituted correlation")),
    )
    monkeypatch.setattr(
        orchestrator, "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("mutation called with substituted correlation")),
    )

    result = orchestrator._execute_managed_recall_event(
        tenant_id="east-bay-food-bank", coordinator_id="COORD-X",
        incident_id="INC-X", recalled_lot_id="LOT-X", notice_text="notice",
        source_event_id="message-x", source_publish_time="2026-08-14T00:00:00Z",
        active_revision="rev08", trace_id="0123456789abcdef0123456789abcdef",
    )

    assert result["hero_loop_status"] == "HALTED_BY_MODEL_ARMOR_SERVICE_FAILURE"
    assert result["ledger_mutation_attempted"] is False


def test_preflight_benign_continues_only_to_next_authorized_stage(monkeypatch):
    monkeypatch.setattr(orchestrator, "_verify_internal_workload", lambda value: None)
    monkeypatch.setattr(orchestrator, "generate_trace_id", lambda: "corr-benign")
    monkeypatch.setattr(
        orchestrator,
        "inspect_recall_notice_with_model_armor",
        lambda text, correlation_id: {
            "status": "APPROVED",
            "safety_verdict": "PASSED",
            "managed_operation": "sanitizeUserPrompt",
            "model_armor_template": "managed-template",
            "filter_match_state": "NO_MATCH_FOUND",
            "correlation_id": correlation_id,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_recall_entities_with_gemini_35",
        lambda text: (_ for _ in ()).throw(AssertionError("Gemini called by WP4 preflight")),
    )
    monkeypatch.setattr(
        orchestrator,
        "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("ledger called by WP4 preflight")),
    )

    result = orchestrator.model_armor_preflight(
        orchestrator.RecallArmorPreflightRequest(notice_text="Altered benign notice"),
    )
    assert result["preflight_status"] == "READY_FOR_GEMINI_ADK_EXTRACTION"
    assert result["next_authorized_stage"] == "GEMINI_ADK_EXTRACTION"
    assert result["gemini_adk_invoked"] is False
    assert result["ledger_mutation_attempted"] is False
    assert result["request_correlation_id"] == "corr-benign"


def test_preflight_injection_rejects_without_gemini_or_ledger(monkeypatch):
    monkeypatch.setattr(orchestrator, "_verify_internal_workload", lambda value: None)
    monkeypatch.setattr(orchestrator, "generate_trace_id", lambda: "corr-injection")
    monkeypatch.setattr(
        orchestrator,
        "inspect_recall_notice_with_model_armor",
        lambda text, correlation_id: {
            "status": "BLOCKED",
            "safety_verdict": "FAILED_SAFETY_SCREENING",
            "managed_operation": "sanitizeUserPrompt",
            "model_armor_template": "managed-template",
            "filter_match_state": "MATCH_FOUND",
            "correlation_id": correlation_id,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "extract_recall_entities_with_gemini_35",
        lambda text: (_ for _ in ()).throw(AssertionError("Gemini called after rejection")),
    )
    monkeypatch.setattr(
        orchestrator,
        "execute_ledger_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("ledger called after rejection")),
    )

    result = orchestrator.model_armor_preflight(
        orchestrator.RecallArmorPreflightRequest(notice_text="Altered injection"),
    )
    assert result["preflight_status"] == "REJECTED_BY_MODEL_ARMOR"
    assert result["next_authorized_stage"] is None
    assert result["gemini_adk_invoked"] is False
    assert result["ledger_mutation_attempted"] is False
    assert result["request_correlation_id"] == "corr-injection"
