from unittest.mock import MagicMock, patch

import httpx

from full_shelf_domain.recall import inspect_recall_notice_with_model_armor


def managed_response(match_state="NO_MATCH_FOUND", invocation="SUCCESS", filters=None):
    response = MagicMock(status_code=200)
    response.json.return_value = {"sanitizationResult": {
        "filterMatchState": match_state,
        "invocationResult": invocation,
        "filterResults": filters or {"pi_and_jailbreak": {
            "piAndJailbreakFilterResult": {
                "executionState": "EXECUTION_SUCCESS", "matchState": match_state,
            }
        }},
    }}
    return response


def call(text, response):
    credentials = MagicMock(token="managed-access-token")
    with patch("httpx.post", return_value=response) as post, patch(
        "google.auth.default", return_value=(credentials, "preflight-hackathon")
    ):
        result = inspect_recall_notice_with_model_armor(text)
    return result, post


def test_benign_notice_requires_managed_no_match():
    notice = "Altered recall for lot ALT-8842"
    result, post = call(notice, managed_response())
    assert result["status"] == "APPROVED"
    assert result["safety_verdict"] == "PASSED"
    assert result["invocation_result"] == "SUCCESS"
    assert result["filter_match_state"] == "NO_MATCH_FOUND"
    assert result["managed_operation"] == "sanitizeUserPrompt"
    assert result["model_armor_location"] == "us-central1"
    assert "notice_text" not in result
    request = post.call_args
    assert request.args[0].endswith(
        "/templates/full-shelf-recall-input-v1:sanitizeUserPrompt"
    )
    assert request.kwargs["json"] == {"userPromptData": {"text": notice}}


def test_prompt_injection_is_blocked_only_from_managed_match():
    result, _ = call(
        "text without any locally recognized phrase",
        managed_response(match_state="MATCH_FOUND"),
    )
    assert result["status"] == "BLOCKED"
    assert result["safety_verdict"] == "FAILED_SAFETY_SCREENING"
    assert result["filter_match_state"] == "MATCH_FOUND"


def test_http_403_fails_closed_without_response_body_leak():
    response = MagicMock(status_code=403, text="sensitive upstream details")
    result, _ = call("altered notice", response)
    assert result["status"] == "SERVICE_UNAVAILABLE"
    assert result["model_armor_api_status"] == 403
    assert "model_armor_api_response" not in result


def test_timeout_fails_closed():
    credentials = MagicMock(token="managed-access-token")
    with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")), patch(
        "google.auth.default", return_value=(credentials, "preflight-hackathon")
    ):
        result = inspect_recall_notice_with_model_armor("altered notice")
    assert result["status"] == "SERVICE_UNAVAILABLE"
    assert result["failure_type"] == "TimeoutException"


def test_malformed_response_fails_closed():
    response = MagicMock(status_code=200)
    response.json.return_value = {"notSanitizationResult": {}}
    result, _ = call("altered notice", response)
    assert result["status"] == "SERVICE_UNAVAILABLE"
    assert result["failure_type"] == "ValueError"


def test_partial_filter_failure_fails_closed():
    filters = {"pi_and_jailbreak": {"piAndJailbreakFilterResult": {
        "executionState": "EXECUTION_FAILED", "matchState": "NO_MATCH_FOUND"
    }}}
    result, _ = call("altered notice", managed_response(filters=filters))
    assert result["status"] == "SERVICE_UNAVAILABLE"


def test_skipped_filter_fails_closed():
    filters = {"pi_and_jailbreak": {"piAndJailbreakFilterResult": {
        "executionState": "EXECUTION_SKIPPED", "matchState": "NO_MATCH_FOUND"
    }}}
    result, _ = call("altered notice", managed_response(filters=filters))
    assert result["status"] == "SERVICE_UNAVAILABLE"
