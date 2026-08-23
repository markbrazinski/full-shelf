"""Recall extraction behavior, proven through the REAL ADK runtime.

This file previously mocked `google.adk.runners.Runner`, which the independent
audit correctly rejected as non-evidence. It now drives the actual coordinator
and the actual Recall Extraction ADK agent, scripting only the Gemini network
call, and asserts the same accepted extraction guarantees as before: strict
schema, source anchoring, explicit lot anchoring, and fail-closed behavior.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fleet_fakes import run_canonical_fleet, scripted_gemini  # noqa: E402

from full_shelf_domain.recall import is_eligible_gemini_model  # noqa: E402


def extract(**gemini_kwargs):
    with scripted_gemini(**gemini_kwargs):
        return run_canonical_fleet()["proposal"]


def test_locked_model_floor_parser():
    assert is_eligible_gemini_model("gemini-3.5-flash")
    assert is_eligible_gemini_model("gemini-4.0-pro")
    assert not is_eligible_gemini_model("gemini-3.4-flash")
    assert not is_eligible_gemini_model("gemini-2.5-flash")
    assert not is_eligible_gemini_model("flash")


def test_recall_extraction_runs_as_a_real_adk_agent_under_the_coordinator():
    proposal = extract()
    assert proposal.status == "PROPOSED"
    assert proposal.extraction["lot_id"] == "LTC-4471"
    assert proposal.extraction["product_name"] == "Romaine Lettuce"
    recall_hop = proposal.delegation_trace[0]
    assert recall_hop["agent_name"] == "RecallExtractionAgent"
    assert recall_hop["parent_agent_id"] == "IncidentCoordinatorAgent"
    assert recall_hop["adk_invocation_id"]
    assert recall_hop["model_used"] == "gemini-3.5-flash"
    assert recall_hop["adk_framework"] == "google-adk/2.6.3"


@pytest.mark.parametrize("text", [
    "not json",
    '{"lot_id":"LTC-4471"}',
    '{"lot_id":"LTC-4471","product_name":"Romaine Lettuce",'
    '"hazard":"E. coli O157:H7","action_required":"PAUSE_DISTRIBUTION",'
    '"source_anchor":"Supplier Safety Bulletin","unapproved":"field"}',
])
def test_invalid_structured_output_requires_manual_review(text):
    proposal = extract(raw_for={"RecallExtractionAgent": text})
    assert proposal.status == "MANUAL_REVIEW_REQUIRED"
    assert proposal.reason_code == "INVALID_STRUCTURED_OUTPUT"


def test_fabricated_value_fails_source_anchor_validation():
    proposal = extract(overrides={"RecallExtractionAgent": {
        "lot_id": "LTC-4471", "product_name": "Canonical Baby Spinach",
        "hazard": "E. coli O157:H7", "action_required": "PAUSE_DISTRIBUTION",
        "source_anchor": "Supplier Safety Bulletin",
    }})
    assert proposal.status == "MANUAL_REVIEW_REQUIRED"
    assert proposal.reason_code == "SOURCE_ANCHOR_VALIDATION_FAILED"


def test_model_error_requires_manual_review_without_fallback():
    proposal = extract(error_for="RecallExtractionAgent")
    assert proposal.status == "MANUAL_REVIEW_REQUIRED"
    assert proposal.reason_code in {"ADK_MODEL_ERROR", "ADK_INVOCATION_FAILED"}
    assert "scripted upstream model failure" not in str(proposal.model_dump())


def test_recall_failure_stops_the_whole_sequence():
    calls = []
    with scripted_gemini(error_for="RecallExtractionAgent", calls=calls):
        proposal = run_canonical_fleet()["proposal"]
    assert proposal.status == "MANUAL_REVIEW_REQUIRED"
    # No downstream specialist may run once extraction fails.
    assert calls == ["RecallExtractionAgent"]
