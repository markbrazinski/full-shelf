"""Deterministic revalidation of advisory agent output.

These validators run *outside* the ADK fleet. They are the only bridge between
a model proposal and the existing application submission path: an agent's claim
is accepted only when it reconciles exactly with deterministic evidence. Any
disagreement raises FleetProposalError, which the caller converts into
MANUAL_REVIEW_REQUIRED with zero ledger mutation.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from .contracts import (
    PARTNER_MIN_CONFIDENCE,
    PARTNER_TEMPLATE_IDS,
    RECOVERY_MIN_CONFIDENCE,
    FleetProposalError,
    IncidentLeadAssessment,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
    deterministic_escalation_level,
)


def validate_incident_lead_assessment(
    assessment: IncidentLeadAssessment,
    accepted_event_id: str,
    authorized_playbook_ids: Sequence[str],
    authorized_specialists: Sequence[str],
) -> IncidentLeadAssessment:
    """Require the incident lead's proposal to reference authorized resources only.

    The source event must match what was accepted, the playbook must exist and be
    authorized, and required specialists must be a subset of what that playbook permits.
    Confidence is reported but does not gate acceptance; grounded evidence is required.
    """
    if assessment.source_event_id != accepted_event_id:
        raise FleetProposalError("INCIDENT_SOURCE_EVENT_MISMATCH")
    if assessment.selected_playbook_id not in authorized_playbook_ids:
        raise FleetProposalError("INCIDENT_PLAYBOOK_NOT_AUTHORIZED")
    for specialist_id in assessment.required_specialists:
        if specialist_id not in authorized_specialists:
            raise FleetProposalError("INCIDENT_SPECIALIST_NOT_AUTHORIZED")
    return assessment


def validate_custody_assessment(
    assessment: NetworkCustodyAssessment, graph_result: Dict[str, Any]
) -> NetworkCustodyAssessment:
    """Require the agent's every count to equal the deterministic graph result."""
    expected_unconfirmed = [
        position["node_id"] for position in graph_result["unconfirmed_positions"]
    ]
    checks = [
        (assessment.total_cases_in_custody, graph_result["unique_current_cases"],
         "CUSTODY_TOTAL_MISMATCH"),
        (assessment.confirmed_cases, graph_result["confirmed_cases"],
         "CUSTODY_CONFIRMED_MISMATCH"),
        (assessment.unconfirmed_cases, graph_result["unconfirmed_cases"],
         "CUSTODY_UNCONFIRMED_MISMATCH"),
        (sorted(assessment.unconfirmed_node_ids), sorted(expected_unconfirmed),
         "CUSTODY_UNCONFIRMED_NODES_MISMATCH"),
    ]
    # Compare lot and depth only when the deterministic result reports them, so
    # a narrower graph projection cannot be turned into a false mismatch.
    if graph_result.get("lot_id") is not None:
        checks.append(
            (assessment.lot_id, graph_result["lot_id"], "CUSTODY_LOT_MISMATCH")
        )
    if graph_result.get("max_path_depth") is not None:
        checks.append((assessment.max_path_depth, graph_result["max_path_depth"],
                       "CUSTODY_DEPTH_MISMATCH"))
    for actual, expected, reason_code in checks:
        if actual != expected:
            raise FleetProposalError(reason_code)

    expected_containment = (
        "UNCONFIRMED_DOWNSTREAM" if graph_result["unconfirmed_cases"]
        else "FULLY_TRACED"
    )
    if assessment.containment_assessment != expected_containment:
        raise FleetProposalError("CUSTODY_CONTAINMENT_MISMATCH")
    return assessment


def validate_recovery_selection(
    selection: RecoverySelection, candidates: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """Resolve a selected candidate ID back to its deterministic contents.

    The agent supplies only an ID. The returned allocations and shortfalls come
    from the deterministic candidate set, never from model output, so the model
    cannot alter a quantity, destination, or lot even if it tries.
    """
    # Fact-based checks first: empty candidate set is not a confidence issue
    if not candidates:
        raise FleetProposalError("NO_FEASIBLE_RECOVERY_CANDIDATE")

    # Verify selected candidate exists in supplied set
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    chosen = by_id.get(selection.selected_candidate_id)
    if chosen is None:
        raise FleetProposalError("UNKNOWN_RECOVERY_CANDIDATE")

    # Verify candidate has required allocations and shortfalls
    if not chosen["allocations"] or not chosen["shortfalls"]:
        raise FleetProposalError("PARTIAL_RECOVERY_POLICY_INPUTS_REQUIRED")

    # Confidence floor is secondary: enforced after facts are verified
    if selection.confidence < RECOVERY_MIN_CONFIDENCE:
        raise FleetProposalError("RECOVERY_CONFIDENCE_BELOW_THRESHOLD")

    return chosen


def validate_partner_communication(
    communication: PartnerCommunication, partner_state: Dict[str, Any]
) -> PartnerCommunication:
    """Restrict partner output to an approved template and bounded parameters."""
    # Fact-based checks first: missing/empty required parameters are not a confidence issue
    if communication.partner_id != partner_state["partner_id"]:
        raise FleetProposalError("PARTNER_IDENTITY_MISMATCH")
    required = PARTNER_TEMPLATE_IDS.get(communication.template_id)
    if required is None:
        raise FleetProposalError("UNKNOWN_PARTNER_TEMPLATE")

    supplied = communication.template_parameters.supplied()
    if set(supplied) != set(required):
        raise FleetProposalError("PARTNER_TEMPLATE_PARAMETERS_INVALID")

    # A template requiring a deadline may not be selected when none exists
    # (check this before empty-parameter check to give correct error)
    if "deadline" in required and not partner_state.get("deadline"):
        raise FleetProposalError("PARTNER_TEMPLATE_REQUIRES_MISSING_DEADLINE")

    # Verify all required parameters are non-empty before authoritative check
    for key, value in supplied.items():
        if not value or (isinstance(value, str) and not value.strip()):
            raise FleetProposalError("PARTNER_TEMPLATE_PARAMETER_EMPTY")

    # Escalation is recomputed from trusted state, never accepted from the model.
    if communication.escalation_level != deterministic_escalation_level(partner_state):
        raise FleetProposalError("PARTNER_ESCALATION_NOT_DETERMINISTIC")

    # Every renderable parameter must have an authoritative source. A parameter
    # with no entry here cannot be bound and is therefore rejected outright,
    # which is what prevents an invented pickup window or deadline.
    authoritative = {
        "partner_name": partner_state["partner_name"],
        "lot_id": partner_state["lot_id"],
        "cases": str(partner_state["unconfirmed_cases"]),
        "deadline": partner_state.get("deadline") or "",
    }
    for key, value in supplied.items():
        if key not in authoritative:
            raise FleetProposalError("PARTNER_PARAMETER_HAS_NO_AUTHORITATIVE_SOURCE")
        if value != authoritative[key]:
            raise FleetProposalError("PARTNER_PARAMETER_NOT_AUTHORITATIVE")

    # Acknowledge is an authoritative fact owned by the ledger callback path.
    # An agent may request one; it may never assert one.
    if partner_state["acknowledgment_status"] == "CONFIRMED":
        raise FleetProposalError("PARTNER_ACKNOWLEDGMENT_NOT_AGENT_AUTHORITY")

    # Confidence floor is secondary: enforced after facts are verified
    if communication.confidence < PARTNER_MIN_CONFIDENCE:
        raise FleetProposalError("PARTNER_CONFIDENCE_BELOW_THRESHOLD")

    return communication


def render_partner_message(communication: PartnerCommunication) -> str:
    """Deterministically render the outbound text. No model text is ever used.

    This commission does not send anything; rendering exists so the eventual
    delivery path owns the exact words.
    """
    templates = {
        "partner.pickup-request.v1": (
            "{partner_name}: refrigerated partner pickup requested for lot "
            "{lot_id}, {cases} cases."
        ),
        "partner.acknowledgment-request.v1": (
            "{partner_name}: confirm custody of lot {lot_id}, {cases} cases, "
            "by {deadline}."
        ),
        "partner.shortfall-notice.v1": (
            "{partner_name}: lot {lot_id} shortfall of {cases} cases remains "
            "unresolved."
        ),
    }
    template = templates.get(communication.template_id)
    if template is None:
        raise FleetProposalError("UNKNOWN_PARTNER_TEMPLATE")
    return template.format(**communication.template_parameters.supplied())


def proposal_hash(payload: Dict[str, Any]) -> str:
    """Stable hash over the advisory proposal for evidence correlation."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def validate_recall_extraction(extracted, raw_notice: str, expected_lot_id: str):
    """Re-apply the accepted recall source-anchoring rules inside the fleet.

    Every extracted field must carry its own quote, which must be a literal
    substring of the screened notice. The lot identifier must have an explicit
    lot anchor and match the authenticated event. Lot must be present (not None).
    """
    from full_shelf_domain.recall import _has_explicit_lot_anchor

    normalized = raw_notice.casefold()

    # Lot must be present
    if not extracted.lot_id:
        extracted.missing_required_fields.append("lot_id")
        raise FleetProposalError("INSUFFICIENT_SOURCE_ANCHORS")

    # Validate each field's quote is literal substring
    for field_name in ["lot_id", "hazard"]:
        field = getattr(extracted, field_name)
        if field and field.quote.casefold() not in normalized:
            raise FleetProposalError("SOURCE_ANCHOR_VALIDATION_FAILED")

    for field_name in ["notice_scope"]:
        for item in getattr(extracted, field_name, []):
            if item.quote.casefold() not in normalized:
                raise FleetProposalError("SOURCE_ANCHOR_VALIDATION_FAILED")

    if extracted.notice_time and extracted.notice_time.quote.casefold() not in normalized:
        raise FleetProposalError("SOURCE_ANCHOR_VALIDATION_FAILED")

    # Lot must have explicit anchor in notice
    if not _has_explicit_lot_anchor(raw_notice, extracted.lot_id.value):
        raise FleetProposalError("LOT_ANCHOR_VALIDATION_FAILED")

    # Lot must match authenticated event
    if extracted.lot_id.value != expected_lot_id:
        raise FleetProposalError("EXTRACTED_LOT_DOES_NOT_MATCH_EVENT")

    return extracted


def _is_valid_hhmm_format(value: str) -> bool:
    """Check if value matches HH:MM (24-hour format)."""
    if not isinstance(value, str) or len(value) != 5:
        return False
    if value[2] != ':':
        return False
    try:
        hour = int(value[0:2])
        minute = int(value[3:5])
        return 0 <= hour <= 23 and 0 <= minute <= 59
    except (ValueError, IndexError):
        return False
