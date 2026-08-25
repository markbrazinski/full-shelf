"""Incident Coordinator: the ADK root agent for `full-shelf.incident-coordinator.v1`.

The coordinator is a concrete ADK custom agent (a `BaseAgent` subclass) that
owns the governed specialist sequence: it decides the order, runs each
specialist, and stops the sequence the moment deterministic validation rejects a
result.

Topology, stated exactly: the coordinator executes under its own `Runner`, and
it drives each specialist through that specialist's OWN `Runner` and OWN ADK
session. This is a separate-Runner topology. It is NOT one nested ADK
invocation, and the four specialists are NOT ADK children of the coordinator
invocation, so no evidence field claims parentage. Each hop records the
coordinator execution that ordered it (`coordinator_agent_id`,
`coordination_run_id`) alongside the specialist's real, distinct
`specialist_run_id` and `specialist_session_id`.

Recall Extraction is ordered first by the coordinator, on Model-Armor-approved
notice text supplied by the caller. Its evidence is its own; it never reuses the
coordinator's session.

The coordinator holds no tools and no model of its own: sequencing an incident
response is a governed procedure, not a generative one. It contains no ledger
submission code and no ledger import. The proposal it returns is advisory;
application code outside this fleet revalidates every field deterministically
and remains the only path to the private ledger.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from .agents import (
    APP_NAME,
    WORKLOAD_USER_ID,
    build_fulfillment_planning_recovery_agent,
    build_incident_lead_agent,
    build_network_custody_agent,
    build_partner_operations_agent,
    build_recall_intake_extraction_agent,
    collect_specialist_output,
    incident_lead_prompt,
    network_custody_prompt,
    partner_prompt,
    recall_prompt,
    recovery_prompt,
)
from .contracts import (
    AGENT_FULFILLMENT_PLANNING_RECOVERY,
    AGENT_INCIDENT_LEAD,
    AGENT_RECALL_INTAKE_EXTRACTION,
    AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
    AGENT_TIMEOUT_SECONDS,
    FleetProposal,
    FleetProposalError,
    IncidentLeadAssessment,
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
from .orchestration import TriggerClass, sequence_for_trigger
from .validation import (
    proposal_hash,
    validate_custody_assessment,
    validate_incident_lead_assessment,
    validate_partner_communication,
    validate_recall_extraction,
    validate_recovery_selection,
)


# Infrastructure identifier for the coordinator itself (not an agent, not in FLEET_AGENT_IDS)
AGENT_INCIDENT_COORDINATOR = "full-shelf.incident-coordinator.v1"

# The RECALL sequence, DERIVED from the single authoritative source in
# orchestration.py. A previously hand-copied duplicate of this tuple silently
# disagreed with ORCHESTRATION_PATHS when the recall path changed, so it is
# derived here rather than restated. Never hand-code a sequence in this module.
_RECALL_SEQUENCE = sequence_for_trigger(TriggerClass.RECALL)
# GOVERNED_SEQUENCE is for backward compatibility only. All new code uses sequence_for_trigger().
GOVERNED_SEQUENCE = _RECALL_SEQUENCE


class FleetRunContext:
    """Immutable deterministic inputs one coordinator invocation may read."""

    __slots__ = ("incident_id", "lot_id", "screened_notice_text", "graph_result",
                 "recovery_candidates", "partner_state", "source_event_id", "source_class",
                 "authorized_playbooks", "authorized_specialists", "trigger_class", "callback_received_at")

    def __init__(self, *, incident_id: str, lot_id: str,
                 screened_notice_text: str, graph_result: Dict[str, Any],
                 recovery_candidates: List[Dict[str, Any]],
                 partner_state: Dict[str, Any],
                 source_event_id: Optional[str] = None,
                 source_class: Optional[str] = None,
                 authorized_playbooks: Optional[List[str]] = None,
                 authorized_specialists: Optional[List[str]] = None,
                 trigger_class: Optional[Any] = None,
                 callback_received_at: Optional[datetime] = None):
        from .orchestration import TriggerClass

        self.incident_id = incident_id
        self.lot_id = lot_id
        self.screened_notice_text = screened_notice_text
        self.graph_result = graph_result
        self.recovery_candidates = recovery_candidates
        self.partner_state = partner_state
        self.source_event_id = source_event_id
        self.source_class = source_class
        self.authorized_playbooks = authorized_playbooks or ["recall-response-playbook-v1"]
        self.authorized_specialists = authorized_specialists or [
            AGENT_RECALL_INTAKE_EXTRACTION,
            AGENT_NETWORK_CUSTODY,
            AGENT_FULFILLMENT_PLANNING_RECOVERY,
            AGENT_PARTNER_OPERATIONS,
        ]
        self.trigger_class = trigger_class or TriggerClass.RECALL
        self.callback_received_at = callback_received_at or datetime.now(timezone.utc)


def _build_hops_for_trigger(
    context: FleetRunContext,
    accepted: Dict[str, Any],
) -> List[tuple]:
    """Build agent sequence (hops) based on trigger class and context.

    Returns list of (agent_id, prompt_builder, validator, ok_label) tuples.
    prompt_builder is a callable that accepts previously accepted outputs.
    Agents are only included if they're in the sequence for this trigger.
    """
    from .orchestration import TriggerClass, sequence_for_trigger

    trigger = context.trigger_class
    agent_sequence = sequence_for_trigger(trigger)

    # Define all possible hop configurations
    # prompt_builder is a callable that accepts `accepted` dict from previous steps
    hop_configs = {
        AGENT_INCIDENT_LEAD: (
            lambda acc: incident_lead_prompt(
                context.source_event_id or "",
                context.source_class or "FOOD_SAFETY_RECALL",
                context.lot_id,
                extraction=acc.get(AGENT_RECALL_INTAKE_EXTRACTION)
            ),
            lambda parsed: validate_incident_lead_assessment(
                parsed, context.source_event_id or "",
                context.authorized_playbooks,
                context.authorized_specialists
            ),
            "INCIDENT_SCOPE_DETERMINED"
        ),
        AGENT_RECALL_INTAKE_EXTRACTION: (
            lambda acc: recall_prompt(context.screened_notice_text),
            lambda parsed: validate_recall_extraction(
                parsed, context.screened_notice_text, context.lot_id
            ),
            "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED"
        ),
        AGENT_NETWORK_CUSTODY: (
            lambda acc: network_custody_prompt(custody_graph_read(context.graph_result)),
            lambda parsed: validate_custody_assessment(
                parsed, context.graph_result
            ),
            "RECONCILED_WITH_DETERMINISTIC_GRAPH"
        ),
        AGENT_FULFILLMENT_PLANNING_RECOVERY: (
            lambda acc: recovery_prompt(recovery_candidates_read(context.recovery_candidates),
                          context.trigger_class),
            lambda parsed: (validate_recovery_selection(
                parsed, context.recovery_candidates
            ), parsed)[1],
            "CANDIDATE_ID_RESOLVED_DETERMINISTICALLY"
        ),
    }

    # Partner Operations outbound communication mode: select template for partner.
    # Inbound partner evidence is handled directly in main.py:process_partner_evidence
    # after Model Armor screening, using partner_evidence.py's run_partner_evidence_agent and
    # verify_partner_custody_proposal. The coordinator does not invoke Partner Operations for callbacks;
    # this route is for outbound template selection only.
    hop_configs[AGENT_PARTNER_OPERATIONS] = (
        lambda acc: partner_prompt(partner_state_read(**context.partner_state)),
        lambda parsed: validate_partner_communication(
            parsed, partner_state_read(**context.partner_state)
        ),
        "TEMPLATE_AND_PARAMETERS_VALIDATED"
    )

    # Build hops only for agents in the sequence
    hops = []
    for agent_id in agent_sequence:
        if agent_id in hop_configs:
            prompt_builder, validator, ok_label = hop_configs[agent_id]
            hops.append((agent_id, prompt_builder, validator, ok_label))

    return hops


def build_incident_coordinator_agent(run_context: Optional[FleetRunContext] = None):
    """Return the concrete ADK custom agent used as the fleet root.

    Built lazily so importing this module never requires ADK at collection time.
    When `run_context` is supplied the coordinator is fully armed: it constructs
    the five specialists and governs their separate executions. Without one it is
    still a valid, inspectable ADK agent.

    One coordinator Runner/session governs five separately correlated
    specialist Runner/session executions. Correlation is application-managed
    through `coordination_run_id`; no native ADK parent-child lineage is
    claimed.
    """
    from google.adk.agents import BaseAgent
    from google.adk.events import Event
    from google.genai import types

    sub_agents = []
    if run_context is not None:
        # Build only the agents needed for this trigger
        agent_ids = sequence_for_trigger(run_context.trigger_class)

        # Partner Operations runs outbound-follow-up only from this coordinator.
        # Inbound partner evidence is governed solely by the authenticated,
        # Model-Armor-screened main.py:process_partner_evidence path and never
        # reaches run_fleet, so no inbound schema is selected here.
        partner_schema = None

        sub_agents_by_id = {
            AGENT_INCIDENT_LEAD: build_incident_lead_agent(),
            AGENT_RECALL_INTAKE_EXTRACTION: build_recall_intake_extraction_agent(),
            AGENT_NETWORK_CUSTODY: build_network_custody_agent([
                build_custody_graph_tool(run_context.graph_result),
                build_custody_dependents_tool(run_context.graph_result),
            ]),
            AGENT_FULFILLMENT_PLANNING_RECOVERY: build_fulfillment_planning_recovery_agent([]),
            AGENT_PARTNER_OPERATIONS: build_partner_operations_agent([], output_schema=partner_schema),
        }
        # Only include agents in the sequence
        sub_agents = [sub_agents_by_id[agent_id] for agent_id in agent_ids]

    class IncidentCoordinatorAgent(BaseAgent):
        """ADK custom agent that sequences the Full Shelf specialist fleet.

        Sequencing happens here, in `_run_async_impl`. Each specialist is
        executed through its own Runner and session; this agent orders those
        executions and correlates them, it does not host them. Deterministic
        validation runs between hops, so a specialist that contradicts
        authoritative evidence stops the sequence before the next specialist is
        asked anything.

        One coordinator Runner/session governs specialists (count varies by trigger)
        in separately correlated Runner/session executions. Correlation is
        application-managed through `coordination_run_id`; no native ADK parent-child
        lineage is claimed.
        """

        async def _run_async_impl(self, ctx) -> AsyncGenerator["Event", None]:
            context: FleetRunContext = self._fleet_run_context
            accepted: Dict[str, Any] = {}
            trace: List[Dict[str, Any]] = []
            failure: Optional[str] = None

            # Build hops based on trigger; only invoke agents needed for this trigger
            hops = _build_hops_for_trigger(context, accepted)

            for index, (agent_id, prompt_builder, validator, ok_label) in enumerate(hops):
                # Build prompt dynamically, using results from previous steps
                prompt = prompt_builder(accepted)
                # Get specialist by index (should match because both derived from same sequence)
                if index >= len(self.sub_agents):
                    failure = "SUB_AGENTS_MISMATCH"
                    break
                specialist = self.sub_agents[index]
                try:
                    started: Dict[str, Any] = {}
                    parsed, execution = await asyncio.wait_for(
                        collect_specialist_output(
                            specialist=specialist, agent_id=agent_id,
                            prompt=prompt, ctx=ctx, started=started,
                            trigger_class=context.trigger_class,
                        ),
                        timeout=AGENT_TIMEOUT_SECONDS[agent_id],
                    )
                except asyncio.TimeoutError:
                    failure = "ADK_TIMEOUT"
                    trace.append(_trace_entry(
                        agent_id=agent_id,
                        coordinator_agent_id=AGENT_INCIDENT_COORDINATOR,
                        coordination_run_id=ctx.invocation_id,
                        execution=_partial_execution(
                            agent_id, specialist, started
                        ),
                        validation=failure,
                    ))
                    break
                except FleetProposalError as exc:
                    failure = exc.reason_code
                    trace.append(_trace_entry(
                        agent_id=agent_id,
                        coordinator_agent_id=AGENT_INCIDENT_COORDINATOR,
                        coordination_run_id=ctx.invocation_id,
                        # A failed specialist still reports the real session and
                        # run it reached before failing.
                        execution=_partial_execution(
                            agent_id, specialist, getattr(exc, "execution", None)
                        ),
                        validation=failure,
                    ))
                    break
                except Exception:
                    # Upstream text is deliberately dropped so no prompt,
                    # document content, or credential can reach evidence.
                    failure = "ADK_INVOCATION_FAILED"
                    trace.append(_trace_entry(
                        agent_id=agent_id,
                        coordinator_agent_id=AGENT_INCIDENT_COORDINATOR,
                        coordination_run_id=ctx.invocation_id,
                        execution=_partial_execution(
                            agent_id, specialist, started
                        ),
                        validation=failure,
                    ))
                    break

                try:
                    accepted[agent_id] = validator(parsed)
                except FleetProposalError as exc:
                    failure = exc.reason_code
                    trace.append(_trace_entry(
                        agent_id=agent_id,
                        coordinator_agent_id=AGENT_INCIDENT_COORDINATOR,
                        coordination_run_id=ctx.invocation_id,
                        execution=execution, validation=failure,
                    ))
                    break
                trace.append(_trace_entry(
                    agent_id=agent_id,
                    coordinator_agent_id=AGENT_INCIDENT_COORDINATOR,
                    coordination_run_id=ctx.invocation_id,
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


def _partial_execution(agent_id, specialist, captured=None):
    """Evidence for a hop that started but did not produce a valid result.

    Prefers the identifiers the specialist actually captured before failing, so
    a failed run is still traceable to its real ADK session and invocation.
    """
    base = {"agent_id": agent_id, "agent_name": specialist.name}
    if captured:
        return {**base, **captured}
    return base


def _trace_entry(
    *, agent_id: str, coordinator_agent_id: str, coordination_run_id: Optional[str],
    execution: Dict[str, Any], validation: str,
) -> Dict[str, Any]:
    """Build one sanitized coordination-evidence record from real execution.

    Field names describe exactly what the runtime does. `coordinator_agent_id`
    and `coordination_run_id` identify the coordinator execution that ordered
    this hop; `specialist_run_id` and `specialist_session_id` are the
    specialist's own ADK identifiers from its own Runner. Nothing here asserts
    an ADK parent/child relationship, because the topology does not create one.
    """
    return {
        "agent_id": agent_id,
        "coordinator_agent_id": coordinator_agent_id,
        "coordination_run_id": coordination_run_id,
        "agent_name": execution.get("agent_name"),
        "model_used": execution.get("model_used"),
        "adk_framework": execution.get("adk_framework"),
        "specialist_run_id": execution.get("specialist_run_id"),
        "specialist_session_id": execution.get("specialist_session_id"),
        "adk_event_id": execution.get("adk_event_id"),
        "declared_tools": execution.get("declared_tools", []),
        "tool_invocations": execution.get("tool_invocations", []),
        "deterministic_validation": validation,
    }


async def _run_coordinator_async(context: FleetRunContext) -> Dict[str, Any]:
    """Run the coordinator execution that governs the specialist executions.

    One coordinator Runner/session execution governs four correlated specialist
    Runner/session executions. Each specialist execution is distinct and carries
    its own session and invocation identifiers, correlated to this coordinator
    run by `coordination_run_id`.
    """
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
        "coordinator_session_id": session.id,
        "coordination_run_id": root_invocation_id,
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
    source_event_id: Optional[str] = None,
    trigger: Optional[str] = None,
    coordinator_runner=None,
) -> Dict[str, Any]:
    """Run one real Incident Coordinator ADK execution and return its proposal.

    One coordinator Runner/session governs specialist Runner/session executions.
    The number and type of specialists invoked depends on the trigger class.
    Correlation is application-managed through `coordination_run_id`; no native
    ADK parent-child lineage is claimed.

    `trigger` specifies which orchestration path to use. Defaults to RECALL for
    backward compatibility. Valid triggers: DAILY_PLANNING, FLEET_FAILURE, RECALL,
    NEXT_DAY_DRAFT. Inbound partner callbacks are not a fleet trigger; they are
    governed solely by main.py:process_partner_evidence.

    Every accepted specialist output is consumed by the assembled proposal. Any
    agent, model, tool, schema, timeout, or reconciliation failure returns a
    MANUAL_REVIEW_REQUIRED proposal; the caller performs zero ledger mutation.

    `coordinator_runner` is injected only by tests that must drive the sequence
    without a live model. The canonical path always uses real ADK execution.
    """
    from .orchestration import TriggerClass

    # Default to RECALL for backward compatibility with existing callers
    if trigger is None:
        trigger_class = TriggerClass.RECALL
    else:
        try:
            trigger_class = TriggerClass(trigger)
        except ValueError:
            return _failed_proposal(
                incident_id, lot_id, "INVALID_TRIGGER_CLASS", []
            )

    context = FleetRunContext(
        incident_id=incident_id, lot_id=lot_id,
        screened_notice_text=screened_notice_text, graph_result=graph_result,
        recovery_candidates=recovery_candidates, partner_state=partner_state,
        source_event_id=source_event_id,
        trigger_class=trigger_class,
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

    from .orchestration import sequence_for_trigger

    accepted = outcome["accepted"]

    # Get the expected agents for this trigger
    trigger_agents = set(sequence_for_trigger(context.trigger_class))
    # Verify that all expected agents for this trigger ran
    if set(accepted) != trigger_agents:
        return _failed_proposal(
            incident_id, lot_id, "INCOMPLETE_SPECIALIST_COVERAGE", trace
        )

    # If Incident Lead ran, verify it authorized all agents that actually ran.
    # Incident Lead's required_specialists must be a superset of agents that ran (minus Incident Lead itself).
    if AGENT_INCIDENT_LEAD in trigger_agents:
        incident_lead_output = accepted.get(AGENT_INCIDENT_LEAD)
        if incident_lead_output:
            authorized_specialists = set(incident_lead_output.required_specialists)
            agents_after_incident_lead = trigger_agents - {AGENT_INCIDENT_LEAD, AGENT_RECALL_INTAKE_EXTRACTION}
            if not agents_after_incident_lead.issubset(authorized_specialists):
                unauthorized = agents_after_incident_lead - authorized_specialists
                return _failed_proposal(
                    incident_id, lot_id,
                    f"PLAYBOOK_DID_NOT_AUTHORIZE_SEQUENCE: {','.join(sorted(unauthorized))}",
                    trace
                )

    # Extract only the outputs for agents that ran (are in trigger_agents)
    proposal_kwargs = {
        "status": "PROPOSED",
        "incident_id": incident_id,
        "lot_id": lot_id,
        "delegation_trace": trace,
        "coordinator_session_id": outcome.get("coordinator_session_id"),
        "coordination_run_id": outcome.get("coordination_run_id"),
    }

    # Optional fields based on which agents ran
    if AGENT_INCIDENT_LEAD in trigger_agents:
        proposal_kwargs["incident_lead"] = accepted[AGENT_INCIDENT_LEAD]

    if AGENT_RECALL_INTAKE_EXTRACTION in trigger_agents:
        proposal_kwargs["extraction"] = accepted[AGENT_RECALL_INTAKE_EXTRACTION].model_dump()

    if AGENT_NETWORK_CUSTODY in trigger_agents:
        proposal_kwargs["custody"] = accepted[AGENT_NETWORK_CUSTODY]

    if AGENT_FULFILLMENT_PLANNING_RECOVERY in trigger_agents:
        proposal_kwargs["recovery"] = accepted[AGENT_FULFILLMENT_PLANNING_RECOVERY]

    if AGENT_PARTNER_OPERATIONS in trigger_agents:
        partner_result = accepted[AGENT_PARTNER_OPERATIONS]
        # Only include partner in proposal if not abstaining
        if not (isinstance(partner_result, dict) and partner_result.get("abstain")):
            proposal_kwargs["partner"] = partner_result

    proposal = FleetProposal(**proposal_kwargs)

    # Only set hash if we have recovery (all recovery objectives require it)
    if AGENT_FULFILLMENT_PLANNING_RECOVERY in trigger_agents:
        recovery = accepted[AGENT_FULFILLMENT_PLANNING_RECOVERY]
        chosen_candidate = next(
            candidate for candidate in recovery_candidates
            if candidate["candidate_id"] == recovery.selected_candidate_id
        )
        hash_payload = {
            "incident_id": incident_id,
            "lot_id": lot_id,
            "selected_candidate_id": recovery.selected_candidate_id,
            "candidate_hash": chosen_candidate.get("content_hash"),
        }
        # Add optional fields to hash if they exist
        if AGENT_NETWORK_CUSTODY in trigger_agents:
            hash_payload["custody"] = accepted[AGENT_NETWORK_CUSTODY].model_dump()
        if AGENT_PARTNER_OPERATIONS in trigger_agents:
            partner_result = accepted[AGENT_PARTNER_OPERATIONS]
            # Only include partner in hash if not abstaining
            if not (isinstance(partner_result, dict) and partner_result.get("abstain")):
                hash_payload["template_id"] = partner_result.template_id
        if AGENT_RECALL_INTAKE_EXTRACTION in trigger_agents:
            hash_payload["extracted_lot_id"] = accepted[AGENT_RECALL_INTAKE_EXTRACTION].lot_id
        proposal.proposal_hash = proposal_hash(hash_payload)
        return {"proposal": proposal, "recovery_candidate": chosen_candidate}
    else:
        # For non-recovery triggers, no recovery candidate
        proposal.proposal_hash = proposal_hash({
            "incident_id": incident_id,
            "lot_id": lot_id,
        })
        return {"proposal": proposal, "recovery_candidate": None}


def _failed_proposal(incident_id, lot_id, reason_code, trace):
    return {
        "proposal": FleetProposal(
            status="MANUAL_REVIEW_REQUIRED", incident_id=incident_id,
            lot_id=lot_id, reason_code=reason_code, delegation_trace=trace,
        ),
        "recovery_candidate": None,
    }
