import pytest
from unittest.mock import patch, MagicMock
from full_shelf_domain.recall import extract_recall_entities_with_gemini_35


def test_adk_runner_extraction_success():
    notice = "FDA Enforcement Report #2026-0807-L4: Urgent recall issued for Lot LTC-4471 (Romaine Lettuce) due to contamination with E. coli O157:H7. Action: PAUSE_DISPATCH_AND_QUARANTINE."

    mock_event = MagicMock()
    mock_part = MagicMock()
    mock_part.text = '{"lot_id": "LTC-4471", "product_name": "Romaine Lettuce", "hazard": "E. coli O157:H7", "action_required": "PAUSE_DISPATCH_AND_QUARANTINE", "source_anchor": "FDA Enforcement Report #2026-0807-L4"}'
    mock_event.content.parts = [mock_part]

    async def _mock_run_async(*args, **kwargs):
        yield mock_event

    mock_runner = MagicMock()
    mock_runner.run_async = _mock_run_async

    mock_session = MagicMock()
    mock_session.id = "test-adk-session-12345"

    async def _mock_create_session(*args, **kwargs):
        return mock_session

    mock_session_service = MagicMock()
    mock_session_service.create_session = _mock_create_session

    with patch("google.adk.runners.Runner", return_value=mock_runner), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        extracted = extract_recall_entities_with_gemini_35(notice)
        assert extracted["lot_id"] == "LTC-4471"
        assert extracted["product_name"] == "Romaine Lettuce"
        assert extracted["adk_framework"] == "GOOGLE_ADK_2.6"
        assert extracted["validation_status"] == "VALIDATED_AGAINST_SOURCE_ANCHOR"


def test_adk_runner_extraction_invalid_json_handled():
    notice = "Invalid notice without JSON"

    mock_event = MagicMock()
    mock_part = MagicMock()
    mock_part.text = 'Not valid JSON'
    mock_event.content.parts = [mock_part]

    async def _mock_run_async(*args, **kwargs):
        yield mock_event

    mock_runner = MagicMock()
    mock_runner.run_async = _mock_run_async

    mock_session = MagicMock()
    mock_session.id = "test-adk-session-invalid"

    async def _mock_create_session(*args, **kwargs):
        return mock_session

    mock_session_service = MagicMock()
    mock_session_service.create_session = _mock_create_session

    with patch("google.adk.runners.Runner", return_value=mock_runner), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        extracted = extract_recall_entities_with_gemini_35(notice)
        assert extracted["status"] == "EXTRACTION_FAILED_MANUAL_REVIEW_REQUIRED"
        assert extracted["validation_status"] == "MANUAL_REVIEW_REQUIRED"
