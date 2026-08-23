"""Incident Coordinator: the ADK root agent for `full-shelf.incident-coordinator.v1`.

The coordinator is a concrete ADK custom agent (a `BaseAgent` subclass) that
genuinely owns the governed specialist sequence. `run_fleet` enters ADK exactly
once, through a real `Runner`, and every specialist invocation happens inside
that single coordinator invocation: each specialist is a declared sub-agent, run
via `ctx`-derived child invocation contexts, so parent/child relationships and
run identifiers come from actual ADK execution rather than from synthesized
records.

Recall Extraction runs first, inside the coordinator, on Model-Armor-approved
notice text supplied by the caller. It is not retro-labeled.

The coordinator holds no tools and no model of its own: sequencing an incident
response is a governed procedure, not a generative one. It contains no ledger
submission code and no ledger import. The proposal it returns is advisory;
application code outside this fleet revalidates every field deterministically
and remains the only path to the private ledger.
"""

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

from .agents import (
    APP_NAME,
    WORKLOAD_USER_ID,
    build_fulfillment_recovery_agent,
    build_network_custody_agent,
    build_partner_operations_agent,
    build_recall_extraction_agent,
    collect_specialist_output,
    network_custody_prompt,
    partner_prompt,
    recall_prompt,
    recovery_prompt,
)
from .contracts import (
    AGENT_FULFILLMENT_RECOVERY,
    AGENT_INCIDENT_COORDINATOR,
    AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
    AGENT_RECALL_EXTRACTION,
    AGENT_TIMEOUT_SECONDS,
    FleetProposal,
    FleetProposalError,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
)
from .tools import (
    build_custody_dependents_tool,
    build_custody_graph_tool,
    custody_graph_read,
    partner_state_read,
    recovery_candidates_read,
)
from .validation import (
    proposal_hash,
    validate_custody_assessment,
    validate_partner_communication,
    validate_recall_extraction,
    validate_recovery_selection,
)


# The governed specialist order the coordinator owns. Declared as data so the
# catalog and the parity tests read the same sequence the runtime executes.
GOVERNED_SEQUENCE = (
    AGENT_RECALL_EXTRACTION,
    AGENT_NETWORK_CUSTODY,
    AGENT_FULFILLMENT_RECOVERY,
    AGENT_PARTNER_OPERATIONS,
)


class FleetRunContext:
    """Immutable deterministic inputs one coordinator invocation may read."""

    __slots__ = ("incident_id", "lot_id", "screened_notice_text", "graph_result",
                 "recovery_candidates", "partner_state")

    def __init__(self, *, incident_id: str, lot_id: str,
                 screened_notice_text: str, graph_result: Dict[str, Any],
                 recovery_candidates: List[Dict[str, Any]],
                 partner_state: Dict[str, Any]):
        self.incident_id = incident_id
        self.lot_id = lot_id
        self.screened_notice_text = screened_notice_text
        self.graph_result = graph_result
        self.recovery_candidates = recovery_candidates
        self.partner_state = partner_state


def build_incident_coordinator_agent(run_context: Optional[FleetRunContext] = None):
    """Return the concrete ADK custom agent used as the fleet root.

    Built lazily so importing this module never requires ADK at collection time.
    When `run_context` is supplied the coordinator is fully armed: it constructs
    its four specialist sub-agents and drives them inside its own ADK
    invocation. Without one it is still a valid, inspectable ADK agent.
    """
    from google.adk.agents import BaseAgent
    from google.adk.events import Event
    from google.genai import types

    sub_agents = []
    if run_context is not None:
        sub_agents = [
            build_recall_extraction_agent(),
            build_network_custody_agent([
                build_custody_graph_tool(run_context.graph_result),
                build_custody_dependents_tool(run_context.graph_result),
            ]),
            build_fulfillment_recovery_agent([]),
            build_partner_operations_agent([]),
        ]

    class IncidentCoordinatorAgent(BaseAgent):
        """ADK custom agent that sequences the Full Shelf specialist fleet.

        Delegation happens here, in `_run_async_impl`, using real ADK child
        invocations. Deterministic validation runs between hops, so a specialist
        that contradicts authoritative evidence stops the sequence before the
        next specialist is asked anything.
        """

        async def _run_async_impl(self, ctx) -> AsyncGenerator["Event", None]:
            context: FleetRunContext = self._fleet_run_context
            accepted: Dict[str, Any] = {}
            trace: List[Dict[str, Any]] = []
            failure: Optional[str] = None

            hops = [
                (AGENT_RECALL_EXTRACTION, recall_prompt(context.screened_notice_text),
                 lambda parsed: validate_recall_extraction(
                     parsed, context.screened_notice_text, context.lot_id
                 ), "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED"),
                (AGENT_NETWORK_CUSTODY,
                 network_custody_prompt(custody_graph_read(context.graph_result)),
                 lambda parsed: validate_custody_assessment(
                     parsed, context.graph_result
                 ), "RECONCILED_WITH_DETERMINISTIC_GRAPH"),
                (AGENT_FULFILLMENT_RECOVERY,
                 recovery_prompt(recovery_candidates_read(context.recovery_candidates)),
                 lambda parsed: (validate_recovery_selection(
                     parsed, context.recovery_candidates
                 ), parsed)[1], "CANDIDATE_ID_RESOLVED_DETERMINISTICALLY"),
                (AGENT_PARTNER_OPERATIONS,
                 partner_prompt(partner_state_read(**context.partner_state)),
                 lambda parsed: validate_partner_communication(
                     parsed, partner_state_read(**context.partner_state)
                 ), "TEMPLATE_AND_PARAMETERS_VALIDATED"),
            ]

            for index, (agent_id, prompt, validator, ok_label) in enumerate(hops):
                specialist = self.sub_agents[index]
                try:
                    parsed, execution = await asyncio.wait_for(
                        collect_specialist_output(
                            specialist=specialist, agent_id=agent_id,
                            prompt=prompt, ctx=ctx,
                        ),
                        timeout=AGENT_TIMEOUT_SECONDS[agent_id],
                    )
                except asyncio.TimeoutError:
                    failure = "ADK_TIMEOUT"
                    trace.append(_trace_entry(
                        agent_id=agent_id, parent_agent_id=self.name,
                        execution={"agent_id": agent_id, "agent_name": specialist.name},
                        validation=failure,
                    ))
                    break
                except FleetProposalError as exc:
                    failure = exc.reason_code
                    trace.append(_trace_entry(
                        agent_id=agent_id, parent_agent_id=self.name,
                        execution={"agent_id": agent_id, "agent_name": specialist.name},
                        validation=failure,
                    ))
                    break
                except Exception:
                    # Upstream text is deliberately dropped so no prompt,
                    # document content, or credential can reach evidence.
                    failure = "ADK_INVOCATION_FAILED"
                    trace.append(_trace_entry(
                        agent_id=agent_id, parent_agent_id=self.name,
                        execution={"agent_id": agent_id, "agent_name": specialist.name},
                        validation=failure,
                    ))
                    break

                try:
                    accepted[agent_id] = validator(parsed)
                except FleetProposalError as exc:
                    failure = exc.reason_code
                    trace.append(_trace_entry(
                        agent_id=agent_id, parent_agent_id=self.name,
                        execution=execution, validation=failure,
                    ))
                    break
                trace.append(_trace_entry(
                    agent_id=agent_id, parent_agent_id=self.name,
                    execution=execution, validation=ok_label,
                ))

            payload = {
                "status": "MANUAL_REVIEW_REQUIRED" if failure else "PROPOSED",
                "reason_code": failure,
                "delegation_trace": trace,
                "accepted_agent_ids": list(accepted),
            }
            # Held on the agent instance so the caller reads exactly what this
            # invocation produced, with no cross-run session state involved.
            object.__setattr__(self, "_last_result",
                               {"payload": payload, "accepted": accepted})
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=json.dumps(payload, default=str))],
                ),
            )

    coordinator = IncidentCoordinatorAgent(
        name="IncidentCoordinatorAgent",
        description=(
            "Root coordinator for Full Shelf recall response. Delegates to the "
            "recall extraction, network and custody, fulfillment and recovery, "
            "and partner operations specialists."
        ),
        sub_agents=sub_agents,
    )
    object.__setattr__(coordinator, "_fleet_run_context", run_context)
    object.__setattr__(coordinator, "_last_result", None)
    return coordinator


def _trace_entry(
    *, agent_id: str, parent_agent_id: Optional[str], execution: Dict[str, Any],
    validation: str,
) -> Dict[str, Any]:
    """Build one sanitized delegation-evidence record from real execution."""
    return {
        "agent_id": agent_id,
        "parent_agent_id": parent_agent_id,
        "agent_name": execution.get("agent_name"),
        "model_used": execution.get("model_used"),
        "adk_framework": execution.get("adk_framework"),
        "adk_invocation_id": execution.get("adk_invocation_id"),
        "adk_event_id": execution.get("adk_event_id"),
        "declared_tools": execution.get("declared_tools", []),
        "tool_invocations": execution.get("tool_invocations", []),
        "deterministic_validation": validation,
    }


async def _run_coordinator_async(context: FleetRunContext) -> Dict[str, Any]:
    """Enter ADK exactly once and let the coordinator own the whole sequence."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    coordinator = build_incident_coordinator_agent(context)
    session_service = InMemorySessionService()
    runner = Runner(
        agent=coordinator, session_service=session_service, app_name=APP_NAME
    )
    session = await session_service.create_session(
        user_id=WORKLOAD_USER_ID, app_name=APP_NAME,
    )
    root_invocation_id = None
    async for event in runner.run_async(
        user_id=WORKLOAD_USER_ID, session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"incident:{context.incident_id}")],
        ),
    ):
        if event.invocation_id:
            root_invocation_id = event.invocation_id
        if event.error_code and event.author == coordinator.name:
            raise FleetProposalError("COORDINATOR_ADK_ERROR",
                                     AGENT_INCIDENT_COORDINATOR)

    stored = coordinator._last_result
    if not stored:
        raise FleetProposalError("COORDINATOR_PRODUCED_NO_RESULT",
                                 AGENT_INCIDENT_COORDINATOR)
    return {
        "payload": stored["payload"],
        "accepted": stored["accepted"],
        "adk_session_id": session.id,
        "adk_invocation_id": root_invocation_id,
        "coordinator_name": coordinator.name,
    }


def run_fleet(
    *,
    incident_id: str,
    lot_id: str,
    screened_notice_text: str,
    graph_result: Dict[str, Any],
    recovery_candidates: List[Dict[str, Any]],
    partner_state: Dict[str, Any],
    coordinator_runner=None,
) -> Dict[str, Any]:
    """Run one real Incident Coordinator ADK execution and return its proposal.

    Every specialist runs inside the coordinator's own ADK invocation, and every
    accepted specialist output is consumed by the assembled proposal. Any agent,
    model, tool, schema, timeout, or reconciliation failure returns a
    MANUAL_REVIEW_REQUIRED proposal; the caller performs zero ledger mutation.

    `coordinator_runner` is injected only by tests that must drive the sequence
    without a live model. The canonical path always uses real ADK execution.
    """
    context = FleetRunContext(
        incident_id=incident_id, lot_id=lot_id,
        screened_notice_text=screened_notice_text, graph_result=graph_result,
        recovery_candidates=recovery_candidates, partner_state=partner_state,
    )
    runner = coordinator_runner or (
        lambda ctx: asyncio.run(
            asyncio.wait_for(
                _run_coordinator_async(ctx),
                timeout=AGENT_TIMEOUT_SECONDS[AGENT_INCIDENT_COORDINATOR],
            )
        )
    )
    try:
        outcome = runner(context)
    except asyncio.TimeoutError:
        return _failed_proposal(incident_id, lot_id, "COORDINATOR_TIMEOUT", [])
    except FleetProposalError as exc:
        return _failed_proposal(incident_id, lot_id, exc.reason_code, [])
    except Exception:
        return _failed_proposal(incident_id, lot_id, "FLEET_EXECUTION_FAILED", [])

    payload = outcome["payload"]
    trace = payload["delegation_trace"]
    if payload["status"] != "PROPOSED":
        return _failed_proposal(
            incident_id, lot_id, payload["reason_code"], trace
        )

    accepted = outcome["accepted"]
    # Every governed specialist must have produced a consumed, validated output.
    if set(accepted) != set(GOVERNED_SEQUENCE):
        return _failed_proposal(
            incident_id, lot_id, "INCOMPLETE_SPECIALIST_COVERAGE", trace
        )

    custody: NetworkCustodyAssessment = accepted[AGENT_NETWORK_CUSTODY]
    recovery: RecoverySelection = accepted[AGENT_FULFILLMENT_RECOVERY]
    partner: PartnerCommunication = accepted[AGENT_PARTNER_OPERATIONS]
    extraction = accepted[AGENT_RECALL_EXTRACTION]
    chosen_candidate = next(
        candidate for candidate in recovery_candidates
        if candidate["candidate_id"] == recovery.selected_candidate_id
    )

    proposal = FleetProposal(
        status="PROPOSED", incident_id=incident_id, lot_id=lot_id,
        extraction=extraction.model_dump(), custody=custody, recovery=recovery,
        partner=partner, delegation_trace=trace,
        coordinator_session_id=outcome.get("adk_session_id"),
        coordinator_invocation_id=outcome.get("adk_invocation_id"),
    )
    proposal.proposal_hash = proposal_hash({
        "incident_id": incident_id, "lot_id": lot_id,
        "custody": custody.model_dump(),
        "selected_candidate_id": recovery.selected_candidate_id,
        "candidate_hash": chosen_candidate.get("content_hash"),
        "template_id": partner.template_id,
        "extracted_lot_id": extraction.lot_id,
    })
    return {"proposal": proposal, "recovery_candidate": chosen_candidate}


def _failed_proposal(incident_id, lot_id, reason_code, trace):
    return {
        "proposal": FleetProposal(
            status="MANUAL_REVIEW_REQUIRED", incident_id=incident_id,
            lot_id=lot_id, reason_code=reason_code, delegation_trace=trace,
        ),
        "recovery_candidate": None,
    }
