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
