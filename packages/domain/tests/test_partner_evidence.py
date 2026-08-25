import json
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import ValidationError

from full_shelf_domain.partner_evidence import (
    PartnerCustodyConfirmationDetails,
    PartnerCustodyProposal,
    run_partner_evidence_agent,
    verify_partner_custody_proposal,
)


DETAILS = PartnerCustodyConfirmationDetails(
    schema_version="partner-custody-confirmation.v1",
    partner_id="PARTNER-AGENCY-01",
    site_id="SITE-01",
    custody_node_id="N-ST01",
    lot_id="LTC-4471",
    expected_cases=8,
    expected_acknowledgment_status="UNCONFIRMED",
    requested_acknowledgment_status="CONFIRMED",
    hold_incident_id="HOLD-01",
    operating_day="2026-08-14",
    source_task_name="projects/p/locations/l/queues/q/tasks/t",
)


def proposal(**claims):
    return PartnerCustodyProposal(
        incident_id="INC-2231",
        partner_id="PARTNER-AGENCY-01",
        site_id="SITE-01",
        custody_node_id="N-ST01",
        work_item_id="WORK-PCF-01",
        expected_acknowledgment_status="UNCONFIRMED",
        requested_acknowledgment_status="CONFIRMED",
        requested_mutation="CONFIRM_CUSTODY",
        rationale="Advisory interpretation only.",
        confidence=0.99,
        **claims,
    )


def verify(source, candidate):
    return verify_partner_custody_proposal(
        source_text=source,
        proposal=candidate,
        work_item_id="WORK-PCF-01",
        details=DETAILS,
        incident_id="INC-2231",
        node_on_hand_cases=8,
        node_name="Site 01",
        incoming_edge_cases=8,
    )


def test_partner_work_item_details_are_strict_and_complete():
    with pytest.raises(ValidationError):
        PartnerCustodyConfirmationDetails.model_validate({
            **DETAILS.model_dump(), "untrusted_override": "CONFIRMED"
        })
    for key in PartnerCustodyConfirmationDetails.model_fields:
        with pytest.raises(ValidationError):
            PartnerCustodyConfirmationDetails.model_validate(
                {k: v for k, v in DETAILS.model_dump().items() if k != key}
            )


def test_vague_response_is_denied_with_zero_qualifying_claims():
    result = verify(
        "We pulled the remaining lettuce. Should be all good.", proposal()
    )
    assert result.decision == "DENIED"
    assert {name: claim.state for name, claim in result.claims.items()} == {
        "lot": "MISSING", "quantity": "MISSING", "location": "MISSING",
        "disposition": "MISSING", "confirmation_time": "MISSING",
    }


def test_complete_response_requires_literal_claim_anchors():
    source = (
        "LTC-4471 · 8 cases · ISOLATED_IN_QUARANTINE at Site 01 · "
        "confirmed at 10:18."
    )
    result = verify(source, proposal(
        lot={"value": "LTC-4471", "quote": "LTC-4471"},
        quantity={"value": 8, "quote": "8 cases"},
        location={"value": "Site 01", "quote": "Site 01"},
        disposition={"value": "ISOLATED_IN_QUARANTINE",
                     "quote": "ISOLATED_IN_QUARANTINE"},
        confirmation_time={"value": "10:18", "quote": "confirmed at 10:18"},
    ))
    assert result.decision == "APPLIED"
    assert all(claim.state == "PRESENT" for claim in result.claims.values())


@pytest.mark.asyncio
async def test_real_adk_runner_persists_only_emitted_identifiers():
    candidate = proposal().model_dump(mode="json")
    from google.adk.models.google_llm import Gemini

    async def fake_generate(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=json.dumps(candidate))],
        ))

    with patch.object(Gemini, "generate_content_async", fake_generate):
        parsed, evidence = await run_partner_evidence_agent("screened input")
    assert parsed.requested_mutation == "CONFIRM_CUSTODY"
    assert evidence["adk_session_id"]
    assert evidence["adk_invocation_id"]
    assert evidence["adk_event_id"]
    assert evidence["adk_framework"] == "google-adk/2.6.1"
    assert not any("run_id" in key for key in evidence)
