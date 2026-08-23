"""Incident Coordinator: the ADK root agent for `full-shelf.incident-coordinator.v1`.

The coordinator is a concrete ADK custom agent (a `BaseAgent` subclass) that owns
delegation order and assembles a structured advisory proposal from its four
specialists. It deliberately holds no tools and no model of its own: sequencing
an incident response is a governed procedure, not a generative one.

It contains no ledger submission code and no ledger import. The proposal it
returns is advisory. Existing application code outside this fleet revalidates
every field deterministically and remains the only path to the private ledger.
"""

from typing import Any, AsyncGenerator, Dict, List, Optional

from .agents import (
    build_fulfillment_recovery_agent,
    build_network_custody_agent,
    build_partner_operations_agent,
    network_custody_prompt,
    partner_prompt,
    recovery_prompt,
    run_specialist_agent,
)
from .contracts import (
    AGENT_FULFILLMENT_RECOVERY,
    AGENT_INCIDENT_COORDINATOR,
    AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
    AGENT_RECALL_EXTRACTION,
    FleetProposal,
    FleetProposalError,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
)
from .tools import (
    custody_dependents_read,
    custody_graph_read,
    partner_state_read,
    recovery_candidates_read,
)
from .validation import (
    proposal_hash,
    validate_custody_assessment,
    validate_partner_communication,
    validate_recovery_selection,
)


def build_incident_coordinator_agent():
    """Return the concrete ADK custom agent used as the fleet root.

    Built lazily so importing this module never requires ADK at collection time.
    """
    from google.adk.agents import BaseAgent
    from google.adk.events import Event

    class IncidentCoordinatorAgent(BaseAgent):
        """ADK custom agent that sequences the Full Shelf specialist fleet."""

        async def _run_async_impl(
            self, ctx
        ) -> AsyncGenerator["Event", None]:  # pragma: no cover - ADK entry point
            # Delegation is executed by `run_fleet`, which owns deterministic
            # validation between hops. This entry point exists so the
            # coordinator is a runtime-invokable ADK agent in its own right.
            from google.genai import types

            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(
                        text="Full Shelf incident coordination is executed through "
                             "the governed fleet sequence."
                    )],
                ),
            )

    return IncidentCoordinatorAgent(
        name="IncidentCoordinatorAgent",
        description=(
            "Root coordinator for Full Shelf recall response. Delegates to the "
            "recall extraction, network and custody, fulfillment and recovery, "
            "and partner operations specialists."
        ),
    )


def _trace_entry(
    *, agent_id: str, parent_agent_id: Optional[str], execution: Dict[str, Any],
    validation: str,
) -> Dict[str, Any]:
    """Build one sanitized delegation-evidence record."""
    return {
        "agent_id": agent_id,
        "parent_agent_id": parent_agent_id,
        "agent_name": execution.get("agent_name"),
        "model_used": execution.get("model_used"),
        "adk_framework": execution.get("adk_framework"),
        "adk_session_id": execution.get("adk_session_id"),
        "adk_run_id": execution.get("adk_run_id"),
        "adk_event_id": execution.get("adk_event_id"),
        "declared_tools": execution.get("declared_tools", []),
        "tool_invocations": execution.get("tool_invocations", []),
        "deterministic_validation": validation,
    }


def run_fleet(
    *,
    incident_id: str,
    lot_id: str,
    graph_result: Dict[str, Any],
    recovery_candidates: List[Dict[str, Any]],
    partner_state: Dict[str, Any],
    extraction_evidence: Optional[Dict[str, Any]] = None,
    runner=run_specialist_agent,
) -> Dict[str, Any]:
    """Run the governed delegation sequence and return an advisory proposal.

    Every specialist result is deterministically revalidated before the next hop
    runs. Any agent, model, tool, schema, or reconciliation failure short-circuits
    to MANUAL_REVIEW_REQUIRED, and the caller performs zero ledger mutation.

    `runner` is injected so tests can drive the sequence without live Gemini.
    """
    delegation_trace: List[Dict[str, Any]] = []

    # Hop 0 — the already-completed recall extraction specialist. It runs ahead
    # of this sequence because its input is untrusted and must clear Model Armor
    # first; recording it here preserves the true parent/child relationship.
    if extraction_evidence:
        delegation_trace.append(_trace_entry(
            agent_id=AGENT_RECALL_EXTRACTION,
            parent_agent_id=AGENT_INCIDENT_COORDINATOR,
            execution={
                "agent_name": "RecallExtractionAgent",
                "model_used": extraction_evidence.get("model_used"),
                "adk_framework": extraction_evidence.get("adk_framework"),
                "adk_session_id": extraction_evidence.get("adk_session_id"),
                "adk_run_id": extraction_evidence.get("adk_run_id"),
                "adk_event_id": extraction_evidence.get("adk_event_id"),
                "declared_tools": [],
                "tool_invocations": [],
            },
            validation=extraction_evidence.get(
                "validation_status", "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED"
            ),
        ))

    def failed(reason_code: str) -> Dict[str, Any]:
        proposal = FleetProposal(
            status="MANUAL_REVIEW_REQUIRED",
            incident_id=incident_id,
            lot_id=lot_id,
            reason_code=reason_code,
            delegation_trace=delegation_trace,
        )
        return {"proposal": proposal, "recovery_candidate": None}

    # Hop 1 — Network and Custody.
    custody_facts = custody_graph_read(graph_result)
    try:
        custody_run = runner(
            agent=build_network_custody_agent([
                lambda: custody_graph_read(graph_result),
                lambda node_id: custody_dependents_read(graph_result, node_id=node_id),
            ]),
            agent_id=AGENT_NETWORK_CUSTODY,
            prompt=network_custody_prompt(custody_facts),
            output_model=NetworkCustodyAssessment,
        )
    except FleetProposalError as exc:
        return failed(exc.reason_code)
    try:
        custody = validate_custody_assessment(custody_run["output"], graph_result)
    except FleetProposalError as exc:
        delegation_trace.append(_trace_entry(
            agent_id=AGENT_NETWORK_CUSTODY,
            parent_agent_id=AGENT_INCIDENT_COORDINATOR,
            execution=custody_run["execution"], validation=exc.reason_code,
        ))
        return failed(exc.reason_code)
    delegation_trace.append(_trace_entry(
        agent_id=AGENT_NETWORK_CUSTODY,
        parent_agent_id=AGENT_INCIDENT_COORDINATOR,
        execution=custody_run["execution"],
        validation="RECONCILED_WITH_DETERMINISTIC_GRAPH",
    ))

    # Hop 2 — Fulfillment and Recovery Planner.
    candidate_projection = recovery_candidates_read(recovery_candidates)
    try:
        recovery_run = runner(
            agent=build_fulfillment_recovery_agent([
                lambda: recovery_candidates_read(recovery_candidates),
            ]),
            agent_id=AGENT_FULFILLMENT_RECOVERY,
            prompt=recovery_prompt(candidate_projection),
            output_model=RecoverySelection,
        )
    except FleetProposalError as exc:
        return failed(exc.reason_code)
    try:
        chosen_candidate = validate_recovery_selection(
            recovery_run["output"], recovery_candidates
        )
    except FleetProposalError as exc:
        delegation_trace.append(_trace_entry(
            agent_id=AGENT_FULFILLMENT_RECOVERY,
            parent_agent_id=AGENT_INCIDENT_COORDINATOR,
            execution=recovery_run["execution"], validation=exc.reason_code,
        ))
        return failed(exc.reason_code)
    delegation_trace.append(_trace_entry(
        agent_id=AGENT_FULFILLMENT_RECOVERY,
        parent_agent_id=AGENT_INCIDENT_COORDINATOR,
        execution=recovery_run["execution"],
        validation="CANDIDATE_ID_RESOLVED_DETERMINISTICALLY",
    ))

    # Hop 3 — Partner Operations.
    bounded_partner_state = partner_state_read(**partner_state)
    try:
        partner_run = runner(
            agent=build_partner_operations_agent([
                lambda: partner_state_read(**partner_state),
            ]),
            agent_id=AGENT_PARTNER_OPERATIONS,
            prompt=partner_prompt(bounded_partner_state),
            output_model=PartnerCommunication,
        )
    except FleetProposalError as exc:
        return failed(exc.reason_code)
    try:
        partner = validate_partner_communication(
            partner_run["output"], bounded_partner_state
        )
    except FleetProposalError as exc:
        delegation_trace.append(_trace_entry(
            agent_id=AGENT_PARTNER_OPERATIONS,
            parent_agent_id=AGENT_INCIDENT_COORDINATOR,
            execution=partner_run["execution"], validation=exc.reason_code,
        ))
        return failed(exc.reason_code)
    delegation_trace.append(_trace_entry(
        agent_id=AGENT_PARTNER_OPERATIONS,
        parent_agent_id=AGENT_INCIDENT_COORDINATOR,
        execution=partner_run["execution"],
        validation="TEMPLATE_AND_PARAMETERS_VALIDATED",
    ))

    proposal = FleetProposal(
        status="PROPOSED",
        incident_id=incident_id,
        lot_id=lot_id,
        custody=custody,
        recovery=recovery_run["output"],
        partner=partner,
        delegation_trace=delegation_trace,
    )
    proposal.proposal_hash = proposal_hash({
        "incident_id": incident_id,
        "lot_id": lot_id,
        "custody": custody.model_dump(),
        "selected_candidate_id": recovery_run["output"].selected_candidate_id,
        "candidate_hash": chosen_candidate.get("content_hash"),
        "template_id": partner.template_id,
    })
    return {"proposal": proposal, "recovery_candidate": chosen_candidate}
