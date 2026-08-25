"""Unmocked-ADK test harness.

The ADK `Runner`, session service, agent classes, tool dispatch, event loop, and
schema handling are all REAL. Only the network call to Gemini is replaced, by
patching `Gemini.generate_content_async` to yield a scripted `LlmResponse`.

This is the distinction the independent audit required: prior tests mocked the
Runner itself and therefore proved nothing about ADK execution. These tests
exercise the true runtime path and are classified STRUCTURALLY_VERIFIED. They
are NOT live-model evidence.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

from google.adk.models.llm_response import LlmResponse
from google.genai import types


CANONICAL_GRAPH = {
    "lot_id": "LTC-4471", "query_engine": "SPANNER_GRAPH_GQL", "max_path_depth": 3,
    "unique_current_cases": 96, "confirmed_cases": 88, "unconfirmed_cases": 8,
    "node_count": 6, "intermediate_subtotals_readded": False,
    "current_positions": [
        {"node_id": "WH-01", "node_type": "WAREHOUSE", "name": "Main Warehouse",
         "on_hand_cases": 24, "acknowledgment_status": "CONFIRMED", "path_depth": 0},
        {"node_id": "SITE-01", "node_type": "SUBSITE", "name": "Site 01",
         "on_hand_cases": 8, "acknowledgment_status": "UNCONFIRMED", "path_depth": 3},
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

CANONICAL_NOTICE = (
    "Supplier Safety Bulletin: recall Lot LTC-4471 for Romaine Lettuce "
    "because of E. coli O157:H7. Action: PAUSE_DISTRIBUTION."
)

CANONICAL_PARTNER_STATE = {
    "partner_id": "SITE-01", "partner_name": "Site 01", "lot_id": "LTC-4471",
    "unconfirmed_cases": 8, "acknowledgment_status": "UNCONFIRMED",
    "deadline": "2026-08-08T17:00:00Z",
}

INCIDENT_LEAD_OK = {
    "incident_class": "FOOD_SAFETY_RECALL",
    "source_event_id": "EVT-001",
    "affected_capabilities": ["cold_chain", "fulfillment"],
    "affected_commitment_ids": ["O202", "O203"],
    "selected_playbook_id": "recall-response-playbook-v1",
    "required_specialists": [
        "full-shelf.network-custody.v2",
        "full-shelf.fulfillment-planning-recovery.v2",
    ],
    "immediate_safety_actions": ["pause_distribution", "notify_sites"],
    "rationale": "Food safety recall scope determined from notice.",
    "confidence": 0.95,
}
RECALL_OK = {
    "source_event_id": "EVT-001",
    "lot_id": {"value": "LTC-4471", "quote": "Lot LTC-4471"},
    "hazard": {"value": "E. coli O157:H7", "quote": "E. coli O157:H7"},
    "notice_scope": [{"value": "Romaine Lettuce", "quote": "Romaine Lettuce"}],
    "notice_time": None,
    "missing_required_fields": [],
}
CUSTODY_OK = {
    "lot_id": "LTC-4471", "total_cases_in_custody": 96, "confirmed_cases": 88,
    "unconfirmed_cases": 8, "unconfirmed_node_ids": ["SITE-01"], "max_path_depth": 3,
    "affected_commitment_ids": ["O202", "O203"], 
    "positions": [
        {"node_id": "WH-01", "quantity": 24, "status": "CONFIRMED", "supporting_edge_ids": []},
        {"node_id": "TR2-O202", "quantity": 22, "status": "CONFIRMED", "supporting_edge_ids": []},
        {"node_id": "PICKUP-O203", "quantity": 20, "status": "CONFIRMED", "supporting_edge_ids": []},
        {"node_id": "AG-01", "quantity": 10, "status": "CONFIRMED", "supporting_edge_ids": []},
        {"node_id": "SITE-01", "quantity": 8, "status": "UNCONFIRMED", "supporting_edge_ids": []},
        {"node_id": "RESCUE", "quantity": 12, "status": "CONFIRMED", "supporting_edge_ids": []},
    ], 
    "unresolved_obligations": [
        {"node_id": "SITE-01", "quantity": 8, "required_evidence": "partner_acknowledgment"}
    ],
    "containment_assessment": "UNCONFIRMED_DOWNSTREAM",
    "narrative": "Eight cases at Site 01 remain unconfirmed.",
}
RECOVERY_OK = {
    "selected_candidate_id": "CAND-LOT-ASC",
    "operating_objective": "RECALL_RECOVERY",
    "affected_commitment_ids": [], "known_shortfalls": [],
    "cited_constraints": ["40 safe cases available"],
    "tradeoffs": "A truthful shortfall remains for the third agency.",
    "rationale": "Only feasible allocation of the available safe stock.",
    "confidence": 0.9,
}
PARTNER_OK = {
    "partner_id": "SITE-01", "template_id": "partner.acknowledgment-request.v1",
    "escalation_level": "URGENT",
    "template_parameters": {
        "partner_name": "Site 01", "lot_id": "LTC-4471", "cases": "8",
        "deadline": "2026-08-08T17:00:00Z",
    },
    "rationale": "Custody is unconfirmed and a deadline exists.", "confidence": 0.9,
}

AGENT_DEFAULTS = {
    "IncidentLeadAgent": INCIDENT_LEAD_OK,
    "RecallIntakeExtractionAgent": RECALL_OK,
    "NetworkAndCustodyAgent": CUSTODY_OK,
    "FulfillmentPlanningRecoveryAgent": RECOVERY_OK,
    "PartnerOperationsAgent": PARTNER_OK,
}


@contextmanager
def scripted_gemini(overrides=None, *, error_for=None, hang_for=None,
                    raw_for=None, calls=None, tool_call_for=None):
    """Patch only the Gemini network call. All ADK machinery stays real.

    overrides: {agent_name: dict}  replace one agent's structured reply
    raw_for:   {agent_name: str}   emit raw (possibly invalid) text
    error_for: agent_name          raise inside the model call
    hang_for:  agent_name          sleep long enough to trip the timeout
    calls:     list                receives each invoked agent name, in order
    tool_call_for: {agent_name: tool_name}  emit a real function call on that
                   agent's FIRST turn, so ADK executes the tool and feeds the
                   response back before the agent answers on its second turn
    """
    from google.adk.models.google_llm import Gemini

    replies = dict(AGENT_DEFAULTS)
    replies.update(overrides or {})
    # Values may be a single tool name or a list of names to call in order,
    # one per turn, before the agent finally answers.
    tool_call_for = {
        agent: ([names] if isinstance(names, str) else list(names))
        for agent, names in (tool_call_for or {}).items()
    }
    tool_turns_taken = {}

    async def fake_generate(self, llm_request, stream=False):
        instruction = llm_request.config.system_instruction or ""
        agent_name = next(
            (name for name in AGENT_DEFAULTS if name in instruction), None
        )
        if agent_name is None:
            raise AssertionError(f"UNIDENTIFIED_AGENT_PROMPT: {instruction[:80]}")
        if calls is not None:
            calls.append(agent_name)
        if error_for == agent_name:
            raise RuntimeError("scripted upstream model failure")
        if hang_for == agent_name:
            import asyncio

            await asyncio.sleep(30)
        # Early turns for a tool-scripted agent request each tool in turn. ADK
        # executes it and calls back with the response, which is the round-trip
        # under test. The agent answers only after the script is exhausted.
        pending = tool_call_for.get(agent_name)
        if pending:
            taken = tool_turns_taken.get(agent_name, 0)
            if taken < len(pending):
                tool_turns_taken[agent_name] = taken + 1
                tool_name = pending[taken]
                args = {"node_id": "WH-01"} if "dependents" in tool_name else {}
                yield LlmResponse(content=types.Content(
                    role="model",
                    parts=[types.Part.from_function_call(
                        name=tool_name, args=args)],
                ))
                return
        if raw_for and agent_name in raw_for:
            text = raw_for[agent_name]
        else:
            text = json.dumps(replies[agent_name])
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part.from_text(text=text)])
        )

    with patch.object(Gemini, "generate_content_async", fake_generate):
        yield


def canonical_candidates():
    from full_shelf_domain.fleet.tools import generate_recovery_candidates

    return generate_recovery_candidates(
        incident_id="INC-CANON", safe_lots=[("LTC-5090", 40)],
        affected_orders=[("O201", "AG-01", 18), ("O202", "AG-02", 22),
                         ("O203", "AG-03", 20)],
    )


def run_canonical_fleet(**kwargs):
    from full_shelf_domain.fleet.coordinator import run_fleet

    params = {
        "incident_id": "INC-CANON", "lot_id": "LTC-4471",
        "screened_notice_text": CANONICAL_NOTICE,
        "graph_result": CANONICAL_GRAPH,
        "recovery_candidates": canonical_candidates(),
        "partner_state": CANONICAL_PARTNER_STATE,
        "source_event_id": "EVT-001",
    }
    params.update(kwargs)
    return run_fleet(**params)
