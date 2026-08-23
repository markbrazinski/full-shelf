"""Concrete Google ADK agent definitions for the Full Shelf five-agent fleet.

Each factory returns a real ADK agent object bound to a strict output schema and
an explicit tool allowlist. Peer and parent transfer are disabled everywhere, so
delegation is owned by the coordinator's explicit sequence rather than by model
discretion.

No agent in this module holds mutation authority. Tools are read-only closures
over data already read by the caller, and the coordinator returns an advisory
proposal that deterministic validation must accept before the existing
application code may submit anything to the private ledger.
"""

import asyncio
import os
from importlib.metadata import version
from typing import Any, Callable, Dict, List, Optional

from pydantic import ValidationError

from .contracts import (
    AGENT_FULFILLMENT_RECOVERY,
    AGENT_RECALL_EXTRACTION,
    AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
    AGENT_TIMEOUT_SECONDS,
    AGENT_TOOL_ALLOWLIST,
    PARTNER_TEMPLATE_IDS,
    FleetProposalError,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
)

MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-3.5-flash")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")
APP_NAME = "FullShelfFleet"
WORKLOAD_USER_ID = "orchestrator-workload"


def adk_framework() -> str:
    return f"google-adk/{version('google-adk')}"


NETWORK_CUSTODY_INSTRUCTION = """
You assess physical custody of a recalled lot for a food bank control plane.

Use only the values returned by your custody tools. Every number you report
must be copied exactly from tool output. Never compute, estimate, adjust, or
re-add an intermediate subtotal, and never recall a scenario from memory.

If the tools report any unconfirmed downstream cases, containment_assessment
must be UNCONFIRMED_DOWNSTREAM. Report FULLY_TRACED only when unconfirmed cases
are exactly zero.

Your narrative must describe only what the tool output shows. Return the
configured structured response and nothing else.
"""

FULFILLMENT_RECOVERY_INSTRUCTION = """
You select one recovery plan for a food bank control plane.

Deterministic planning code has already produced the complete set of feasible
candidates. You may only choose one existing candidate_id from that set. You
may not invent a candidate, alter any quantity, destination, lot, vehicle,
deadline, or plan revision, and you may not restate those values.

Prefer the candidate that serves the most agencies and leaves the smallest
truthful shortfall. Cite the specific constraints that drove the choice and
state the tradeoff honestly, including any shortfall that remains.

If no candidate is acceptable, still return the closest candidate_id with a low
confidence value. Return the configured structured response and nothing else.
"""

PARTNER_OPERATIONS_INSTRUCTION = """
You choose how to contact an operational partner for a food bank control plane.

You may only select one approved template_id from the supplied list and supply
its exact required parameters, copied verbatim from the partner state given to
you. You may not write outbound prose; deterministic code renders the message.

You may never acknowledge inventory, confirm cases, close an incident, or
assert that a partner has responded. If the partner state shows custody is
already confirmed, or you are unsure which template applies, return a
confidence at or below 0.5.

Escalation level is URGENT when custody is unconfirmed and a deadline exists,
PRIORITY when custody is unconfirmed without a deadline, and ROUTINE otherwise.

Return the configured structured response and nothing else.
"""

COORDINATOR_INSTRUCTION = """
You are the incident coordinator for a food bank control plane. You delegate to
specialist agents in a fixed order and assemble their structured findings. You
never compute quantities, never decide policy, and never submit a command.
"""


def _build_llm_agent(
    *,
    name: str,
    instruction: str,
    output_schema,
    tools: List[Callable],
    max_output_tokens: int,
):
    """Construct one strict, non-transferring ADK LlmAgent."""
    from google.adk.agents import Agent
    from google.adk.planners import BuiltInPlanner
    from google.genai import types

    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
    os.environ["GOOGLE_CLOUD_LOCATION"] = VERTEX_LOCATION

    kwargs: Dict[str, Any] = {
        "name": name,
        "model": MODEL_ID,
        "instruction": instruction,
        "output_schema": output_schema,
        "planner": BuiltInPlanner(
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
        "disallow_transfer_to_parent": True,
        "disallow_transfer_to_peers": True,
        "generate_content_config": types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=max_output_tokens,
        ),
    }
    if tools:
        kwargs["tools"] = tools
    return Agent(**kwargs)


def build_network_custody_agent(tools: List[Callable]):
    """Concrete ADK LlmAgent for `full-shelf.network-custody.v1`."""
    return _build_llm_agent(
        name="NetworkAndCustodyAgent",
        instruction=NETWORK_CUSTODY_INSTRUCTION,
        output_schema=NetworkCustodyAssessment,
        tools=tools,
        max_output_tokens=1024,
    )


def build_fulfillment_recovery_agent(tools: List[Callable]):
    """Concrete ADK LlmAgent for `full-shelf.fulfillment-recovery.v1`."""
    return _build_llm_agent(
        name="FulfillmentAndRecoveryPlannerAgent",
        instruction=FULFILLMENT_RECOVERY_INSTRUCTION,
        output_schema=RecoverySelection,
        tools=tools,
        max_output_tokens=1024,
    )


def build_partner_operations_agent(tools: List[Callable]):
    """Concrete ADK LlmAgent for `full-shelf.partner-operations.v1`."""
    return _build_llm_agent(
        name="PartnerOperationsAgent",
        instruction=PARTNER_OPERATIONS_INSTRUCTION,
        output_schema=PartnerCommunication,
        tools=tools,
        max_output_tokens=1024,
    )


def _recall_schema():
    from full_shelf_domain.recall import RecallExtractionSchema

    return RecallExtractionSchema


AGENT_OUTPUT_MODELS = {
    AGENT_RECALL_EXTRACTION: _recall_schema,
    AGENT_NETWORK_CUSTODY: lambda: NetworkCustodyAssessment,
    AGENT_FULFILLMENT_RECOVERY: lambda: RecoverySelection,
    AGENT_PARTNER_OPERATIONS: lambda: PartnerCommunication,
}


class AgentRunFailure(FleetProposalError):
    """One specialist run failed. Carries only a stable reason code."""


RECALL_EXTRACTION_INSTRUCTION = """
Extract the requested fields only from the supplied recall notice.
Every value must be explicitly supported by text in that notice.
Do not infer missing values, use remembered examples, or invent a
canonical scenario. Return the configured structured response only.
"""


def build_recall_extraction_agent(tools: Optional[List[Any]] = None):
    """Concrete ADK LlmAgent for `full-shelf.recall-extraction.v1`.

    Preserves the accepted extraction behavior: strict schema, zero tools, no
    transfer, deterministic decoding. Source anchoring is enforced by
    `validation.validate_recall_extraction` after parsing.
    """
    from full_shelf_domain.recall import RecallExtractionSchema

    return _build_llm_agent(
        name="RecallExtractionAgent",
        instruction=RECALL_EXTRACTION_INSTRUCTION,
        output_schema=RecallExtractionSchema,
        tools=tools or [],
        max_output_tokens=512,
    )


async def collect_specialist_output(*, specialist, agent_id: str, prompt: str, ctx):
    """Run one specialist as a real ADK invocation and parse its structured output.

    The specialist executes through a real `Runner` over its own session, which
    is what appends model and tool-response events so ADK's flow loop can
    converge on a final response. Driving `agent.run_async(ctx)` directly would
    bypass that append step and deadlock any agent that calls a tool.

    `ctx` is the coordinator's invocation context; it supplies the parent
    session service so specialist runs stay inside the coordinator's own ADK
    execution rather than opening an unrelated one. Returns the parsed output
    model plus sanitized execution evidence. Raw prompts, model text, and
    reasoning are never returned.
    """
    from google.adk.runners import Runner
    from google.genai import types

    output_model = AGENT_OUTPUT_MODELS[agent_id]()
    execution: Dict[str, Any] = {
        "agent_id": agent_id,
        "agent_name": specialist.name,
        "model_used": MODEL_ID,
        "vertex_location": VERTEX_LOCATION,
        "adk_framework": adk_framework(),
        "adk_invocation_id": None,
        "adk_event_id": None,
        "tool_invocations": [],
        "declared_tools": list(AGENT_TOOL_ALLOWLIST[agent_id]),
    }

    session_service = ctx.session_service
    runner = Runner(
        agent=specialist, session_service=session_service, app_name=APP_NAME
    )
    session = await session_service.create_session(
        user_id=WORKLOAD_USER_ID, app_name=APP_NAME
    )
    final_texts: List[str] = []
    async for event in runner.run_async(
        user_id=WORKLOAD_USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=prompt)]
        ),
    ):
        if event.invocation_id:
            execution["adk_invocation_id"] = event.invocation_id
        if event.error_code:
            raise AgentRunFailure("ADK_MODEL_ERROR", agent_id)
        for call in (event.get_function_calls() or []):
            execution["tool_invocations"].append(
                {"tool_name": call.name, "outcome": "REQUESTED"}
            )
        for response in (event.get_function_responses() or []):
            execution["tool_invocations"].append(
                {"tool_name": response.name, "outcome": "COMPLETED"}
            )
        if event.author != specialist.name or not event.is_final_response():
            continue
        finish_reason = getattr(event.finish_reason, "name", event.finish_reason)
        if finish_reason not in {None, "STOP", "FINISH_REASON_UNSPECIFIED"}:
            raise AgentRunFailure("ADK_RESPONSE_INCOMPLETE", agent_id)
        text = "".join(
            part.text or "" for part in (event.content.parts if event.content else [])
        ).strip()
        if text:
            final_texts.append(text)
            execution["adk_event_id"] = event.id

    if not execution["adk_invocation_id"]:
        raise AgentRunFailure("ADK_RUN_IDENTIFIER_MISSING", agent_id)
    if len(final_texts) != 1:
        raise AgentRunFailure("ADK_FINAL_RESPONSE_COUNT_INVALID", agent_id)
    try:
        parsed = output_model.model_validate_json(final_texts[0])
    except ValidationError:
        raise AgentRunFailure("INVALID_STRUCTURED_OUTPUT", agent_id)
    return parsed, execution


def recall_prompt(screened_notice_text: str) -> str:
    """Model-Armor-APPROVED notice text. Screening happens before the fleet."""
    return screened_notice_text


def network_custody_prompt(custody_facts: Dict[str, Any]) -> str:
    """Trusted, normalized custody facts. Model Armor is NOT_APPLICABLE here."""
    return (
        "Assess custody for the recalled lot using these authoritative tool "
        f"facts:\n{custody_facts}\n"
        "Report the counts exactly as given."
    )


def recovery_prompt(candidate_projection: Dict[str, Any]) -> str:
    """Trusted, deterministic candidate set. Model Armor is NOT_APPLICABLE here."""
    return (
        "Select exactly one candidate_id from this deterministic candidate set:\n"
        f"{candidate_projection}\n"
        "You may not modify any value inside a candidate."
    )


# Exact authoritative source for each renderable template parameter. Stated in
# the prompt so the agent copies values rather than omitting or inventing them;
# `validate_partner_communication` independently enforces the same binding.
PARTNER_PARAMETER_SOURCES = {
    "partner_name": "partner_name",
    "lot_id": "lot_id",
    "cases": "unconfirmed_cases",
    "deadline": "deadline",
}


def partner_prompt(partner_state: Dict[str, Any]) -> str:
    """Trusted, bounded partner state. Model Armor is NOT_APPLICABLE here."""
    bindings = {
        parameter: str(partner_state.get(field) or "")
        for parameter, field in PARTNER_PARAMETER_SOURCES.items()
    }
    return (
        f"Partner state:\n{partner_state}\n"
        f"Approved templates and their required parameters:\n"
        f"{ {k: list(v) for k, v in PARTNER_TEMPLATE_IDS.items()} }\n"
        "Select one template_id. Then populate template_parameters with EVERY "
        "required parameter for that template, copying each value exactly from "
        "this binding table. Never leave template_parameters empty, never omit "
        "a required parameter, and never write your own value:\n"
        f"{bindings}"
    )
