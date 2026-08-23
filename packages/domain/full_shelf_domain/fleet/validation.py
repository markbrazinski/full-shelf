"""Deterministic revalidation of advisory agent output.

These validators run *outside* the ADK fleet. They are the only bridge between
a model proposal and the existing application submission path: an agent's claim
is accepted only when it reconciles exactly with deterministic evidence. Any
disagreement raises FleetProposalError, which the caller converts into
MANUAL_REVIEW_REQUIRED with zero ledger mutation.
"""

import hashlib
import json
from typing import Any, Dict, Sequence

from .contracts import (
    PARTNER_MIN_CONFIDENCE,
    PARTNER_TEMPLATE_IDS,
    RECOVERY_MIN_CONFIDENCE,
    FleetProposalError,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
)


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
    if not candidates:
        raise FleetProposalError("NO_FEASIBLE_RECOVERY_CANDIDATE")
    if selection.confidence < RECOVERY_MIN_CONFIDENCE:
        raise FleetProposalError("RECOVERY_CONFIDENCE_BELOW_THRESHOLD")
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    chosen = by_id.get(selection.selected_candidate_id)
    if chosen is None:
        raise FleetProposalError("UNKNOWN_RECOVERY_CANDIDATE")
    if not chosen["allocations"] or not chosen["shortfalls"]:
        raise FleetProposalError("PARTIAL_RECOVERY_POLICY_INPUTS_REQUIRED")
    return chosen


def validate_partner_communication(
    communication: PartnerCommunication, partner_state: Dict[str, Any]
) -> PartnerCommunication:
    """Restrict partner output to an approved template and bounded parameters."""
    if communication.confidence < PARTNER_MIN_CONFIDENCE:
        raise FleetProposalError("PARTNER_CONFIDENCE_BELOW_THRESHOLD")
    if communication.partner_id != partner_state["partner_id"]:
        raise FleetProposalError("PARTNER_IDENTITY_MISMATCH")
    required = PARTNER_TEMPLATE_IDS.get(communication.template_id)
    if required is None:
        raise FleetProposalError("UNKNOWN_PARTNER_TEMPLATE")
    if set(communication.template_parameters) != set(required):
        raise FleetProposalError("PARTNER_TEMPLATE_PARAMETERS_INVALID")

    # Bound every parameter that has an authoritative counterpart. The agent may
    # not restate a case count, lot, or partner name of its own invention.
    authoritative = {
        "partner_name": partner_state["partner_name"],
        "lot_id": partner_state["lot_id"],
        "cases": str(partner_state["unconfirmed_cases"]),
        "deadline": partner_state.get("deadline") or "",
    }
    for key, expected in authoritative.items():
        if key in communication.template_parameters:
            if communication.template_parameters[key] != expected:
                raise FleetProposalError("PARTNER_PARAMETER_NOT_AUTHORITATIVE")

    # Acknowledgment is an authoritative fact owned by the ledger callback path.
    # An agent may request one; it may never assert one.
    if partner_state["acknowledgment_status"] == "CONFIRMED":
        raise FleetProposalError("PARTNER_ACKNOWLEDGMENT_NOT_AGENT_AUTHORITY")
    return communication


def render_partner_message(communication: PartnerCommunication) -> str:
    """Deterministically render the outbound text. No model text is ever used.

    This commission does not send anything; rendering exists so the eventual
    delivery path owns the exact words.
    """
    templates = {
        "partner.pickup-request.v1": (
            "{partner_name}: refrigerated partner pickup requested for lot "
            "{lot_id}, {cases} cases, window {pickup_window}."
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
    return template.format(**communication.template_parameters)


def proposal_hash(payload: Dict[str, Any]) -> str:
    """Stable hash over the advisory proposal for evidence correlation."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
