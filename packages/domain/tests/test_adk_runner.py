from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from full_shelf_domain.recall import (
    MODEL_ID,
    RecallExtractionSchema,
    extract_recall_entities_with_gemini_35,
    is_eligible_gemini_model,
)


NOTICE = (
    "Supplier Safety Bulletin SB-8842: recall Lot ALT-8842 for Green Beans "
    "because of Listeria monocytogenes. Action: PAUSE_DISTRIBUTION."
)
VALID_JSON = (
    '{"lot_id":"ALT-8842","product_name":"Green Beans",'
    '"hazard":"Listeria monocytogenes","action_required":"PAUSE_DISTRIBUTION",'
    '"source_anchor":"Supplier Safety Bulletin SB-8842"}'
)


def event(
    text=VALID_JSON,
    *,
    invocation_id="adk-run-123",
    event_id="adk-event-456",
    error_code=None,
    finish_reason="STOP",
):
    return SimpleNamespace(
        invocation_id=invocation_id,
        error_code=error_code,
        finish_reason=finish_reason,
        author="RecallExtractionAgent",
        content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
        id=event_id,
        usage_metadata=SimpleNamespace(
            prompt_token_count=40,
            candidates_token_count=25,
            total_token_count=65,
        ),
        is_final_response=lambda: True,
    )


def invoke(events=None, *, runner_error=None):
    mock_agent = SimpleNamespace(name="RecallExtractionAgent")
    mock_runner = MagicMock()

    async def run_async(*args, **kwargs):
        if runner_error:
            raise runner_error
        for item in events or [event()]:
            yield item

    mock_runner.run_async = run_async
    mock_session = SimpleNamespace(id="adk-session-789")

    async def create_session(*args, **kwargs):
        return mock_session

    mock_session_service = MagicMock()
    mock_session_service.create_session = create_session

    with patch("google.adk.agents.Agent", return_value=mock_agent) as agent_cls, patch(
        "google.adk.runners.Runner", return_value=mock_runner
    ), patch(
        "google.adk.sessions.InMemorySessionService",
        return_value=mock_session_service,
    ):
        result = extract_recall_entities_with_gemini_35(
            NOTICE,
            correlation_id="corr-wp5-test",
        )
    return result, agent_cls


def test_locked_model_floor_parser():
    assert is_eligible_gemini_model("gemini-3.5-flash")
    assert is_eligible_gemini_model("gemini-4.0-pro")
    assert not is_eligible_gemini_model("gemini-3.4-flash")
    assert not is_eligible_gemini_model("gemini-2.5-flash")
    assert not is_eligible_gemini_model("flash")


def test_adk_runner_is_load_bearing_and_preserves_real_identifiers():
    extracted, agent_cls = invoke()

    assert extracted["status"] == "EXTRACTION_VALIDATED"
    assert extracted["lot_id"] == "ALT-8842"
    assert extracted["product_name"] == "Green Beans"
    assert extracted["model_used"] == "gemini-3.5-flash"
    assert extracted["adk_session_id"] == "adk-session-789"
    assert extracted["adk_run_id"] == "adk-run-123"
    assert extracted["adk_event_id"] == "adk-event-456"
    assert extracted["correlation_id"] == "corr-wp5-test"
    assert extracted["downstream_allowed"] is True
    assert extracted["validation_status"] == "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED"
    assert extracted["token_usage"] == {
        "prompt_tokens": 40,
        "output_tokens": 25,
        "total_tokens": 65,
    }
    assert agent_cls.call_args.kwargs["model"] == MODEL_ID
    assert agent_cls.call_args.kwargs["output_schema"] is RecallExtractionSchema
    assert agent_cls.call_args.kwargs["planner"].thinking_config.thinking_budget == 0
    assert agent_cls.call_args.kwargs["disallow_transfer_to_parent"] is True
    assert agent_cls.call_args.kwargs["disallow_transfer_to_peers"] is True


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"lot_id":"ALT-8842"}',
        VALID_JSON[:-1] + ',"unapproved":"field"}',
    ],
)
def test_invalid_structured_output_requires_manual_review(text):
    extracted, _ = invoke([event(text=text)])
    assert extracted["status"] == "MANUAL_REVIEW_REQUIRED"
    assert extracted["reason_code"] == "INVALID_STRUCTURED_OUTPUT"
    assert extracted["downstream_allowed"] is False
    assert "error_detail" not in extracted


def test_fabricated_value_fails_source_anchor_validation():
    fabricated = VALID_JSON.replace("Green Beans", "Canonical Romaine")
    extracted, _ = invoke([event(text=fabricated)])
    assert extracted["status"] == "MANUAL_REVIEW_REQUIRED"
    assert extracted["reason_code"] == "SOURCE_ANCHOR_VALIDATION_FAILED"
    assert extracted["downstream_allowed"] is False


def test_adk_model_error_requires_manual_review():
    extracted, _ = invoke([event(error_code="MODEL_ERROR")])
    assert extracted["status"] == "MANUAL_REVIEW_REQUIRED"
    assert extracted["reason_code"] == "ADK_MODEL_ERROR"
    assert extracted["downstream_allowed"] is False


def test_adk_runtime_failure_requires_manual_review_without_fallback():
    extracted, _ = invoke(runner_error=RuntimeError("sensitive upstream text"))
    assert extracted["status"] == "MANUAL_REVIEW_REQUIRED"
    assert extracted["reason_code"] == "ADK_INVOCATION_FAILED"
    assert extracted["adk_session_id"] == "adk-session-789"
    assert extracted["downstream_allowed"] is False
    assert "sensitive upstream text" not in str(extracted)


def test_missing_adk_run_identifier_requires_manual_review():
    extracted, _ = invoke([event(invocation_id="")])
    assert extracted["status"] == "MANUAL_REVIEW_REQUIRED"
    assert extracted["reason_code"] == "ADK_RUN_IDENTIFIER_MISSING"
    assert extracted["downstream_allowed"] is False


def test_truncated_adk_response_requires_manual_review():
    extracted, _ = invoke([event(text='{"lot_id":"', finish_reason="MAX_TOKENS")])
    assert extracted["status"] == "MANUAL_REVIEW_REQUIRED"
    assert extracted["reason_code"] == "ADK_RESPONSE_INCOMPLETE"
    assert extracted["downstream_allowed"] is False
