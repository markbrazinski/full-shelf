"""Deterministic revalidation boundaries for advisory agent output."""

import pytest

from full_shelf_domain.fleet.contracts import (
    FleetProposalError,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
)
from full_shelf_domain.fleet.tools import (
    custody_dependents_read,
    custody_graph_read,
    generate_recovery_candidates,
    partner_state_read,
)
from full_shelf_domain.fleet.validation import (
    render_partner_message,
    validate_custody_assessment,
    validate_partner_communication,
    validate_recovery_selection,
)


CANONICAL_GRAPH = {
    "lot_id": "LTC-4471",
    "query_engine": "SPANNER_GRAPH_GQL",
    "unique_current_cases": 96,
    "confirmed_cases": 88,
    "unconfirmed_cases": 8,
    "max_path_depth": 3,
    "node_count": 6,
    "intermediate_subtotals_readded": False,
    "current_positions": [
        {"node_id": "WH-01", "node_type": "WAREHOUSE", "name": "Main Warehouse",
         "on_hand_cases": 24, "acknowledgment_status": "CONFIRMED", "path_depth": 0},
        {"node_id": "TRK-02", "node_type": "VEHICLE", "name": "Truck 2",
         "on_hand_cases": 22, "acknowledgment_status": "CONFIRMED", "path_depth": 1},
        {"node_id": "STG-01", "node_type": "STAGING", "name": "Staging",
         "on_hand_cases": 20, "acknowledgment_status": "CONFIRMED", "path_depth": 1},
        {"node_id": "AG-01", "node_type": "AGENCY", "name": "Agency 01",
         "on_hand_cases": 10, "acknowledgment_status": "CONFIRMED", "path_depth": 2},
        {"node_id": "SITE-01", "node_type": "SUBSITE", "name": "Site 01",
         "on_hand_cases": 8, "acknowledgment_status": "UNCONFIRMED", "path_depth": 3},
        {"node_id": "DR-01", "node_type": "DIRECT_RESCUE", "name": "Direct Rescue",
         "on_hand_cases": 12, "acknowledgment_status": "CONFIRMED", "path_depth": 1},
    ],
    "unconfirmed_positions": [
        {"node_id": "SITE-01", "node_type": "SUBSITE", "name": "Site 01",
         "on_hand_cases": 8, "acknowledgment_status": "UNCONFIRMED", "path_depth": 3},
    ],
    "paths": [
        {"root_node_id": "WH-01", "destination_node_id": "AG-01", "path_depth": 2},
        {"root_node_id": "WH-01", "destination_node_id": "SITE-01", "path_depth": 3},
    ],
}


def custody_assessment(**overrides):
    payload = {
        "lot_id": "LTC-4471", "total_cases_in_custody": 96, "confirmed_cases": 88,
        "unconfirmed_cases": 8, "unconfirmed_node_ids": ["SITE-01"],
        "max_path_depth": 3, "containment_assessment": "UNCONFIRMED_DOWNSTREAM",
        "narrative": "Site 01 has not confirmed custody of eight cases.",
    }
    payload.update(overrides)
    return NetworkCustodyAssessment(**payload)


# --- Custody anchoring ------------------------------------------------------


def test_custody_projection_never_leaks_query_shape():
    facts = custody_graph_read(CANONICAL_GRAPH)
    assert "query_shape" not in facts
    assert "query_parameters" not in facts
    assert facts["total_cases_in_custody"] == 96
    assert facts["unconfirmed_node_ids"] == ["SITE-01"]


def test_custody_assessment_matching_deterministic_graph_is_accepted():
    assert validate_custody_assessment(custody_assessment(), CANONICAL_GRAPH)


@pytest.mark.parametrize("overrides,reason", [
    ({"total_cases_in_custody": 114}, "CUSTODY_TOTAL_MISMATCH"),
    ({"confirmed_cases": 96}, "CUSTODY_CONFIRMED_MISMATCH"),
    ({"unconfirmed_cases": 0, "containment_assessment": "FULLY_TRACED"},
     "CUSTODY_UNCONFIRMED_MISMATCH"),
    ({"unconfirmed_node_ids": ["AG-03"]}, "CUSTODY_UNCONFIRMED_NODES_MISMATCH"),
    ({"max_path_depth": 9}, "CUSTODY_DEPTH_MISMATCH"),
    ({"lot_id": "LTC-5090"}, "CUSTODY_LOT_MISMATCH"),
])
def test_invented_graph_facts_are_refused(overrides, reason):
    with pytest.raises(FleetProposalError) as exc:
        validate_custody_assessment(custody_assessment(**overrides), CANONICAL_GRAPH)
    assert exc.value.reason_code == reason


def test_false_containment_claim_is_refused():
    # The agent claims full tracing while eight cases remain unconfirmed.
    with pytest.raises(FleetProposalError) as exc:
        validate_custody_assessment(
            custody_assessment(containment_assessment="FULLY_TRACED"),
            CANONICAL_GRAPH,
        )
    assert exc.value.reason_code == "CUSTODY_CONTAINMENT_MISMATCH"


def test_dependents_tool_reports_downstream_only():
    result = custody_dependents_read(CANONICAL_GRAPH, node_id="WH-01")
    assert result["tool_outcome"] == "OK"
    assert [d["node_id"] for d in result["dependents"]] == ["AG-01", "SITE-01"]
    assert custody_dependents_read(
        CANONICAL_GRAPH, node_id="UNKNOWN"
    )["tool_outcome"] == "NOT_FOUND"


# --- Recovery candidate boundary -------------------------------------------


CANONICAL_CANDIDATES = generate_recovery_candidates(
    incident_id="INC-CANON",
    safe_lots=[("LTC-5090", 40)],
    affected_orders=[("O201", "AG-01", 18), ("O202", "AG-02", 22),
                     ("O203", "AG-03", 20)],
)


def selection(**overrides):
    payload = {
        "selected_candidate_id": "CAND-LOT-ASC",
        "operating_objective": "RECALL_RECOVERY",
        "rationale": "Serves both agencies fully within available safe stock.",
        "cited_constraints": ["safe stock 40 cases", "three affected orders"],
        "tradeoffs": "A truthful shortfall remains for the third agency.",
        "confidence": 0.9,
    }
    payload.update(overrides)
    return RecoverySelection(**payload)


def test_canonical_scenario_yields_exactly_one_truthful_candidate():
    assert len(CANONICAL_CANDIDATES) == 1
    candidate = CANONICAL_CANDIDATES[0]
    assert candidate["total_allocated_cases"] == 40
    assert candidate["total_shortfall_cases"] == 20
    assert [(a["agency_id"], a["cases"]) for a in candidate["allocations"]] == [
        ("AG-01", 18), ("AG-02", 22)
    ]
    assert [(s["agency_id"], s["cases"]) for s in candidate["shortfalls"]] == [
        ("AG-03", 20)
    ]


def test_selected_candidate_contents_come_from_deterministic_code():
    chosen = validate_recovery_selection(selection(), CANONICAL_CANDIDATES)
    assert chosen["allocations"] is CANONICAL_CANDIDATES[0]["allocations"]
    assert chosen["shortfalls"] is CANONICAL_CANDIDATES[0]["shortfalls"]


def test_unknown_candidate_id_is_refused():
    with pytest.raises(FleetProposalError) as exc:
        validate_recovery_selection(
            selection(selected_candidate_id="CAND-INVENTED"), CANONICAL_CANDIDATES
        )
    assert exc.value.reason_code == "UNKNOWN_RECOVERY_CANDIDATE"


def test_low_confidence_selection_is_refused():
    with pytest.raises(FleetProposalError) as exc:
        validate_recovery_selection(selection(confidence=0.2), CANONICAL_CANDIDATES)
    assert exc.value.reason_code == "RECOVERY_CONFIDENCE_BELOW_THRESHOLD"


def test_empty_candidate_set_is_refused():
    with pytest.raises(FleetProposalError) as exc:
        validate_recovery_selection(selection(), [])
    assert exc.value.reason_code == "NO_FEASIBLE_RECOVERY_CANDIDATE"


def test_planner_schema_cannot_express_a_quantity():
    # Any attempt to smuggle a case count into the selection fails the schema.
    with pytest.raises(Exception):
        RecoverySelection(
            selected_candidate_id="CAND-LOT-ASC", rationale="r",
            cited_constraints=["c"], tradeoffs="t", confidence=0.9, cases=99,
        )


def test_noncanonical_scenario_offers_a_real_choice():
    candidates = generate_recovery_candidates(
        incident_id="INC-ALT",
        safe_lots=[("LTS-100", 15), ("LTS-200", 30)],
        affected_orders=[("OA", "AG-A", 20), ("OB", "AG-B", 30)],
    )
    assert len(candidates) == 2
    ids = {c["candidate_id"] for c in candidates}
    assert ids == {"CAND-LOT-ASC", "CAND-LOT-DEEPEST-FIRST"}
    # Distinct allocation content, identical truthful totals: a real planning
    # tradeoff rather than an arithmetic difference.
    assert candidates[0]["content_hash"] != candidates[1]["content_hash"]
    for candidate in candidates:
        assert candidate["total_allocated_cases"] == 45
        assert candidate["total_shortfall_cases"] == 5


# --- Partner boundary -------------------------------------------------------


PARTNER_STATE = partner_state_read(
    partner_id="SITE-01", partner_name="Site 01", lot_id="LTC-4471",
    unconfirmed_cases=8, acknowledgment_status="UNCONFIRMED",
    deadline="2026-08-08T17:00:00Z",
)


def communication(**overrides):
    payload = {
        "partner_id": "SITE-01",
        "template_id": "partner.acknowledgment-request.v1",
        "escalation_level": "URGENT",
        "template_parameters": {
            "partner_name": "Site 01", "lot_id": "LTC-4471", "cases": "8",
            "deadline": "2026-08-08T17:00:00Z",
        },
        "rationale": "Custody is unconfirmed and a deadline exists.",
        "confidence": 0.9,
    }
    payload.update(overrides)
    return PartnerCommunication(**payload)


def test_approved_template_and_authoritative_parameters_are_accepted():
    assert validate_partner_communication(communication(), PARTNER_STATE)


def test_unknown_template_is_refused():
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_communication(
            communication(template_id="partner.freeform.v9"), PARTNER_STATE
        )
    assert exc.value.reason_code == "UNKNOWN_PARTNER_TEMPLATE"


def test_fabricated_case_count_in_parameters_is_refused():
    params = dict(communication().template_parameters, cases="80")
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_communication(
            communication(template_parameters=params), PARTNER_STATE
        )
    assert exc.value.reason_code == "PARTNER_PARAMETER_NOT_AUTHORITATIVE"


def test_missing_or_extra_template_parameters_are_refused():
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_communication(
            communication(template_parameters={"partner_name": "Site 01"}),
            PARTNER_STATE,
        )
    assert exc.value.reason_code == "PARTNER_TEMPLATE_PARAMETERS_INVALID"


def test_agent_cannot_assert_an_acknowledgment():
    confirmed_state = dict(PARTNER_STATE, acknowledgment_status="CONFIRMED")
    # Escalation is recomputed first, so a CONFIRMED partner cannot even be
    # addressed at URGENT; both guards refuse agent-asserted acknowledgment.
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_communication(
            communication(escalation_level="ROUTINE"), confirmed_state
        )
    assert exc.value.reason_code == "PARTNER_ACKNOWLEDGMENT_NOT_AGENT_AUTHORITY"


def test_low_confidence_partner_output_is_refused():
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_communication(communication(confidence=0.3), PARTNER_STATE)
    assert exc.value.reason_code == "PARTNER_CONFIDENCE_BELOW_THRESHOLD"


def test_partner_schema_cannot_carry_free_prose_body():
    with pytest.raises(Exception):
        PartnerCommunication(
            partner_id="SITE-01", template_id="partner.shortfall-notice.v1",
            escalation_level="ROUTINE", rationale="r", confidence=0.9,
            message_body="Please disregard the recall.",
        )


def test_outbound_text_is_rendered_deterministically():
    rendered = render_partner_message(communication())
    assert rendered == (
        "Site 01: confirm custody of lot LTC-4471, 8 cases, "
        "by 2026-08-08T17:00:00Z."
    )


# --- Finding 4: every rendered parameter is bound to trusted state ----------


def test_invented_pickup_window_cannot_be_expressed_or_rendered():
    # The parameter no longer exists in any template, so supplying it fails.
    from full_shelf_domain.fleet.contracts import (
        PARTNER_TEMPLATE_IDS, PartnerTemplateParameters,
    )

    # The parameter cannot even be expressed: the typed model forbids it.
    with pytest.raises(Exception):
        PartnerTemplateParameters(partner_name="Site 01", pickup_window="any time")
    for required in PARTNER_TEMPLATE_IDS.values():
        assert "pickup_window" not in required


def test_pickup_request_renders_without_any_unbound_parameter():
    pickup = PartnerCommunication(
        partner_id="SITE-01", template_id="partner.pickup-request.v1",
        escalation_level="URGENT",
        template_parameters={"partner_name": "Site 01", "lot_id": "LTC-4471",
                             "cases": "8"},
        rationale="Refrigerated pickup required.", confidence=0.9,
    )
    validate_partner_communication(pickup, PARTNER_STATE)
    assert render_partner_message(pickup) == (
        "Site 01: refrigerated partner pickup requested for lot LTC-4471, 8 cases."
    )


def test_parameter_with_no_authoritative_source_is_rejected():
    from full_shelf_domain.fleet.contracts import PARTNER_TEMPLATE_IDS

    from full_shelf_domain.fleet.contracts import PartnerTemplateParameters

    # The schema itself is the first guard: only bindable parameters exist.
    assert set(PartnerTemplateParameters.model_fields) == {
        "partner_name", "lot_id", "cases", "deadline",
    }
    with pytest.raises(Exception):
        PartnerTemplateParameters(invented="anything")


@pytest.mark.parametrize("level", ["ROUTINE", "PRIORITY"])
def test_model_chosen_escalation_must_match_deterministic_policy(level):
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_communication(
            communication(escalation_level=level), PARTNER_STATE
        )
    assert exc.value.reason_code == "PARTNER_ESCALATION_NOT_DETERMINISTIC"


def test_escalation_is_derived_from_trusted_state_only():
    from full_shelf_domain.fleet.contracts import deterministic_escalation_level

    assert deterministic_escalation_level(PARTNER_STATE) == "URGENT"
    assert deterministic_escalation_level(
        dict(PARTNER_STATE, deadline=None)
    ) == "PRIORITY"
    assert deterministic_escalation_level(
        dict(PARTNER_STATE, acknowledgment_status="CONFIRMED")
    ) == "ROUTINE"


def test_deadline_template_cannot_be_used_when_no_deadline_exists():
    no_deadline = dict(PARTNER_STATE, deadline=None)
    params = dict(communication().template_parameters, deadline="")
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_communication(
            communication(template_parameters=params, escalation_level="PRIORITY"),
            no_deadline,
        )
    assert exc.value.reason_code == "PARTNER_TEMPLATE_REQUIRES_MISSING_DEADLINE"


def test_invented_partner_identity_is_refused():
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_communication(
            communication(partner_id="SITE-99"), PARTNER_STATE
        )
    assert exc.value.reason_code == "PARTNER_IDENTITY_MISMATCH"


# --- Partner inbound interpretation ----------------------------------------


def test_partner_inbound_interpretation_with_all_required_anchors():
    """Inbound interpretation must include all five critical source anchors."""
    from full_shelf_domain.fleet.contracts import (
        PartnerInboundInterpretation,
        PartnerEvidenceClaim,
    )
    from full_shelf_domain.fleet.validation import validate_partner_inbound_interpretation

    interpretation = PartnerInboundInterpretation(
        partner_id="SITE-01",
        response_received_at="2026-08-25T14:30:00Z",
        claims=[
            PartnerEvidenceClaim(
                claim_type="lot_id",
                value="LTC-4471",
                source_anchor="Lot LTC-4471"
            ),
            PartnerEvidenceClaim(
                claim_type="quantity",
                value="8",
                source_anchor="8 cases on hand"
            ),
            PartnerEvidenceClaim(
                claim_type="location",
                value="Walk-in cooler, Section B",
                source_anchor="stored in our walk-in cooler, Section B"
            ),
            PartnerEvidenceClaim(
                claim_type="disposition",
                value="held_pending_guidance",
                source_anchor="holding pending your guidance"
            ),
            PartnerEvidenceClaim(
                claim_type="confirmation_time",
                value="2026-08-25T14:25:00Z",
                source_anchor="confirmed at 2:25 PM today"
            ),
        ],
        abstain=False,
        rationale="All critical facts present with explicit source anchors.",
    )
    result = validate_partner_inbound_interpretation(interpretation, "LTC-4471")
    assert result == interpretation


def test_partner_inbound_missing_source_anchors_is_refused():
    """Missing any of the five required source anchors must be refused."""
    from full_shelf_domain.fleet.contracts import (
        PartnerInboundInterpretation,
        PartnerEvidenceClaim,
    )
    from full_shelf_domain.fleet.validation import validate_partner_inbound_interpretation

    # Missing: location, disposition, confirmation_time
    interpretation = PartnerInboundInterpretation(
        partner_id="SITE-01",
        response_received_at="2026-08-25T14:30:00Z",
        claims=[
            PartnerEvidenceClaim(
                claim_type="lot_id",
                value="LTC-4471",
                source_anchor="Lot LTC-4471"
            ),
            PartnerEvidenceClaim(
                claim_type="quantity",
                value="8",
                source_anchor="8 cases"
            ),
        ],
        abstain=False,  # Critical facts missing
        rationale="Incomplete response from partner.",
    )
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_inbound_interpretation(interpretation, "LTC-4471")
    assert "PARTNER_MISSING_SOURCE_ANCHORS" in exc.value.reason_code


def test_partner_inbound_abstention_prevents_mutation():
    """When abstain=True, no proposal mutation is proposed."""
    from full_shelf_domain.fleet.contracts import PartnerInboundInterpretation
    from full_shelf_domain.fleet.validation import validate_partner_inbound_interpretation

    interpretation = PartnerInboundInterpretation(
        partner_id="SITE-01",
        response_received_at="2026-08-25T14:30:00Z",
        claims=[],
        abstain=True,  # Critical facts missing, not confidence-based
        rationale="Partner response too vague to extract required facts.",
    )
    result = validate_partner_inbound_interpretation(interpretation, "LTC-4471")
    assert result["abstain"] is True
    assert result["partner_id"] == "SITE-01"


def test_partner_inbound_lot_mismatch_is_refused():
    """Lot ID from partner must match the authenticated event lot."""
    from full_shelf_domain.fleet.contracts import (
        PartnerInboundInterpretation,
        PartnerEvidenceClaim,
    )
    from full_shelf_domain.fleet.validation import validate_partner_inbound_interpretation

    interpretation = PartnerInboundInterpretation(
        partner_id="SITE-01",
        response_received_at="2026-08-25T14:30:00Z",
        claims=[
            PartnerEvidenceClaim(
                claim_type="lot_id",
                value="LTC-5090",  # Mismatch
                source_anchor="Lot LTC-5090"
            ),
            PartnerEvidenceClaim(
                claim_type="quantity",
                value="8",
                source_anchor="8 cases"
            ),
            PartnerEvidenceClaim(
                claim_type="location",
                value="Walk-in",
                source_anchor="walk-in"
            ),
            PartnerEvidenceClaim(
                claim_type="disposition",
                value="held",
                source_anchor="held"
            ),
            PartnerEvidenceClaim(
                claim_type="confirmation_time",
                value="2026-08-25T14:25:00Z",
                source_anchor="2:25 PM"
            ),
        ],
        abstain=False,
        rationale="Partner reported different lot.",
    )
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_inbound_interpretation(interpretation, "LTC-4471")
    assert exc.value.reason_code == "PARTNER_LOT_MISMATCH"


def test_partner_inbound_duplicate_claim_type_is_refused():
    """Duplicate claim types with potentially conflicting values must be refused."""
    from full_shelf_domain.fleet.contracts import (
        PartnerInboundInterpretation,
        PartnerEvidenceClaim,
    )
    from full_shelf_domain.fleet.validation import validate_partner_inbound_interpretation

    # Two quantity claims with different values
    interpretation = PartnerInboundInterpretation(
        partner_id="SITE-01",
        response_received_at="2026-08-25T14:30:00Z",
        claims=[
            PartnerEvidenceClaim(
                claim_type="lot_id",
                value="LTC-4471",
                source_anchor="Lot LTC-4471"
            ),
            PartnerEvidenceClaim(
                claim_type="quantity",
                value="8",
                source_anchor="8 cases"
            ),
            PartnerEvidenceClaim(
                claim_type="quantity",
                value="12",
                source_anchor="12 cases"
            ),
            PartnerEvidenceClaim(
                claim_type="location",
                value="Walk-in",
                source_anchor="walk-in"
            ),
            PartnerEvidenceClaim(
                claim_type="disposition",
                value="held",
                source_anchor="held"
            ),
            PartnerEvidenceClaim(
                claim_type="confirmation_time",
                value="2026-08-25T14:25:00Z",
                source_anchor="2:25 PM"
            ),
        ],
        abstain=False,
        rationale="Contradictory evidence.",
    )
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_inbound_interpretation(interpretation, "LTC-4471")
    assert "PARTNER_DUPLICATE_CLAIM_TYPE" in exc.value.reason_code


def test_partner_inbound_malformed_timestamp_is_refused():
    """Malformed response_received_at must be rejected at Pydantic construction."""
    from pydantic import ValidationError
    from full_shelf_domain.fleet.contracts import PartnerInboundInterpretation

    # Invalid timestamp: impossible date 2026-99-99
    with pytest.raises(ValidationError) as exc:
        PartnerInboundInterpretation(
            partner_id="SITE-01",
            response_received_at="2026-99-99T99:99:99garbage",
            claims=[],
            abstain=True,
            rationale="Test",
        )
    # Pydantic raises ValidationError due to field validator
    assert "response_received_at" in str(exc.value).lower()


def test_partner_inbound_timestamp_outside_clock_skew_is_refused():
    """Timestamp far outside infrastructure clock skew must be refused."""
    from datetime import datetime, timezone, timedelta
    from full_shelf_domain.fleet.contracts import PartnerInboundInterpretation, PartnerEvidenceClaim
    from full_shelf_domain.fleet.validation import validate_partner_inbound_interpretation

    infra_time = datetime(2026, 8, 25, 14, 30, 0, tzinfo=timezone.utc)
    # Model's claimed time is 200 seconds in the past (exceeds 60-second skew)
    model_time = infra_time - timedelta(seconds=200)

    interpretation = PartnerInboundInterpretation(
        partner_id="SITE-01",
        response_received_at=model_time.isoformat(),
        claims=[
            PartnerEvidenceClaim(
                claim_type="lot_id",
                value="LTC-4471",
                source_anchor="Lot LTC-4471"
            ),
            PartnerEvidenceClaim(
                claim_type="quantity",
                value="8",
                source_anchor="8 cases"
            ),
            PartnerEvidenceClaim(
                claim_type="location",
                value="Walk-in",
                source_anchor="walk-in"
            ),
            PartnerEvidenceClaim(
                claim_type="disposition",
                value="held",
                source_anchor="held"
            ),
            PartnerEvidenceClaim(
                claim_type="confirmation_time",
                value="2026-08-25T14:25:00Z",
                source_anchor="2:25 PM"
            ),
        ],
        abstain=False,
        rationale="Test",
    )
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_inbound_interpretation(interpretation, "LTC-4471", received_at=infra_time)
    assert "PARTNER_RESPONSE_RECEIVED_AT_CLOCK_SKEW_EXCEEDED" in exc.value.reason_code


def test_partner_inbound_quantity_mismatch_against_authoritative_state_is_refused():
    """Claimed quantity must match authoritative unconfirmed_cases."""
    from full_shelf_domain.fleet.contracts import (
        PartnerInboundInterpretation,
        PartnerEvidenceClaim,
    )
    from full_shelf_domain.fleet.validation import validate_partner_inbound_interpretation

    interpretation = PartnerInboundInterpretation(
        partner_id="SITE-01",
        response_received_at="2026-08-25T14:30:00Z",
        claims=[
            PartnerEvidenceClaim(
                claim_type="lot_id",
                value="LTC-4471",
                source_anchor="Lot LTC-4471"
            ),
            PartnerEvidenceClaim(
                claim_type="quantity",
                value="12",  # Authoritative is 8
                source_anchor="12 cases"
            ),
            PartnerEvidenceClaim(
                claim_type="location",
                value="Walk-in",
                source_anchor="walk-in"
            ),
            PartnerEvidenceClaim(
                claim_type="disposition",
                value="held",
                source_anchor="held"
            ),
            PartnerEvidenceClaim(
                claim_type="confirmation_time",
                value="2026-08-25T14:25:00Z",
                source_anchor="2:25 PM"
            ),
        ],
        abstain=False,
        rationale="Test",
    )
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_inbound_interpretation(
            interpretation, "LTC-4471", expected_quantity=8
        )
    assert exc.value.reason_code == "PARTNER_QUANTITY_NOT_AUTHORITATIVE"


def test_partner_inbound_location_mismatch_against_authoritative_state_is_refused():
    """Claimed location must match authoritative custody node location."""
    from full_shelf_domain.fleet.contracts import (
        PartnerInboundInterpretation,
        PartnerEvidenceClaim,
    )
    from full_shelf_domain.fleet.validation import validate_partner_inbound_interpretation

    interpretation = PartnerInboundInterpretation(
        partner_id="SITE-01",
        response_received_at="2026-08-25T14:30:00Z",
        claims=[
            PartnerEvidenceClaim(
                claim_type="lot_id",
                value="LTC-4471",
                source_anchor="Lot LTC-4471"
            ),
            PartnerEvidenceClaim(
                claim_type="quantity",
                value="8",
                source_anchor="8 cases"
            ),
            PartnerEvidenceClaim(
                claim_type="location",
                value="Freezer",  # Authoritative is "Walk-in cooler, Section B"
                source_anchor="in our Freezer"
            ),
            PartnerEvidenceClaim(
                claim_type="disposition",
                value="held",
                source_anchor="held"
            ),
            PartnerEvidenceClaim(
                claim_type="confirmation_time",
                value="2026-08-25T14:25:00Z",
                source_anchor="2:25 PM"
            ),
        ],
        abstain=False,
        rationale="Test",
    )
    with pytest.raises(FleetProposalError) as exc:
        validate_partner_inbound_interpretation(
            interpretation, "LTC-4471", expected_location="Walk-in cooler, Section B"
        )
    assert exc.value.reason_code == "PARTNER_LOCATION_NOT_AUTHORITATIVE"
