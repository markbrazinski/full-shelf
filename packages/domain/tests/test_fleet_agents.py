"""Per-agent boundary tests for the five concrete ADK agents.

Each specialist is exercised through a fake ADK Runner so schema, tool
allowlist, trust boundary, timeout, and failure behavior are proven without a
live Gemini call. Live invocation evidence is a managed-deployment concern and
is deliberately not claimed here.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from full_shelf_domain.fleet import agents, contracts
from full_shelf_domain.fleet.contracts import (
    AGENT_FULFILLMENT_RECOVERY,
    AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
    FleetProposalError,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
)


CUSTODY_JSON = (
    '{"lot_id":"LTC-4471","total_cases_in_custody":96,"confirmed_cases":88,'
    '"unconfirmed_cases":8,"unconfirmed_node_ids":["SITE-01"],'
    '"max_path_depth":3,"containment_assessment":"UNCONFIRMED_DOWNSTREAM",'
    '"narrative":"Eight cases downstream of Agency 01 remain unconfirmed."}'
)


def adk_event(
    text=CUSTODY_JSON,
    *,
    author="NetworkAndCustodyAgent",
    invocation_id="run-1",
    event_id="event-1",
    error_code=None,
    finish_reason="STOP",
    function_calls=None,
    function_responses=None,
):
    return SimpleNamespace(
        invocation_id=invocation_id,
        error_code=error_code,
        finish_reason=finish_reason,
        author=author,
        content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
        id=event_id,
        get_function_calls=lambda: function_calls or [],
        get_function_responses=lambda: function_responses or [],
        is_final_response=lambda: True,
    )


def run_with_fake_adk(*, agent_name, agent_id, output_model, events, prompt="p"):
    """Drive `run_specialist_agent` against a fake Runner/session service."""
    agent = SimpleNamespace(name=agent_name)
    runner = MagicMock()

    async def run_async(*args, **kwargs):
        for item in events:
            yield item

    runner.run_async = run_async
    session_service = MagicMock()

    async def create_session(*args, **kwargs):
        return SimpleNamespace(id="session-1")

    session_service.create_session = create_session

    with patch("google.adk.runners.Runner", return_value=runner), patch(
        "google.adk.sessions.InMemorySessionService", return_value=session_service
    ):
        return agents.run_specialist_agent(
            agent=agent, agent_id=agent_id, prompt=prompt,
            output_model=output_model,
        )


# --- Concrete agent definitions --------------------------------------------


def test_five_concrete_agent_ids_are_declared():
    assert len(contracts.FLEET_AGENT_IDS) == 5
    assert contracts.FLEET_AGENT_IDS == (
        "full-shelf.incident-coordinator.v1",
        "full-shelf.network-custody.v1",
        "full-shelf.fulfillment-recovery.v1",
        "full-shelf.partner-operations.v1",
        "full-shelf.recall-extraction.v1",
    )


def test_coordinator_is_a_concrete_adk_base_agent():
    from google.adk.agents import BaseAgent

    from full_shelf_domain.fleet.coordinator import build_incident_coordinator_agent

    agent = build_incident_coordinator_agent()
    assert isinstance(agent, BaseAgent)
    assert agent.name == "IncidentCoordinatorAgent"


@pytest.mark.parametrize(
    "builder,expected_name,schema",
    [
        (agents.build_network_custody_agent, "NetworkAndCustodyAgent",
         NetworkCustodyAssessment),
        (agents.build_fulfillment_recovery_agent,
         "FulfillmentAndRecoveryPlannerAgent", RecoverySelection),
        (agents.build_partner_operations_agent, "PartnerOperationsAgent",
         PartnerCommunication),
    ],
)
def test_specialists_are_concrete_adk_llm_agents(builder, expected_name, schema):
    from google.adk.agents import LlmAgent

    agent = builder([])
    assert isinstance(agent, LlmAgent)
    assert agent.name == expected_name
    assert agent.output_schema is schema
    assert agent.model == agents.MODEL_ID
    # No specialist may hand control to a peer or back to the parent; the
    # coordinator owns delegation order explicitly.
    assert agent.disallow_transfer_to_parent is True
    assert agent.disallow_transfer_to_peers is True


def test_coordinator_holds_no_tools_and_no_ledger_code():
    import inspect

    from full_shelf_domain.fleet import coordinator

    source = inspect.getsource(coordinator)
    assert contracts.AGENT_TOOL_ALLOWLIST[
        contracts.AGENT_INCIDENT_COORDINATOR
    ] == ()
    for forbidden in ("execute_ledger_command", "post_to_plan_ledger",
                      "LedgerExecutor", "PLAN_LEDGER_URL"):
        assert forbidden not in source


# --- Schema and validation boundaries --------------------------------------


def test_network_custody_output_validates_and_carries_adk_identifiers():
    result = run_with_fake_adk(
        agent_name="NetworkAndCustodyAgent", agent_id=AGENT_NETWORK_CUSTODY,
        output_model=NetworkCustodyAssessment, events=[adk_event()],
    )
    assert result["output"].total_cases_in_custody == 96
    assert result["execution"]["adk_session_id"] == "session-1"
    assert result["execution"]["adk_run_id"] == "run-1"
    assert result["execution"]["adk_event_id"] == "event-1"
    assert result["execution"]["agent_id"] == AGENT_NETWORK_CUSTODY


def test_tool_invocations_are_recorded_as_sanitized_evidence():
    call = SimpleNamespace(name="custody_graph_read")
    response = SimpleNamespace(name="custody_graph_read")
    result = run_with_fake_adk(
        agent_name="NetworkAndCustodyAgent", agent_id=AGENT_NETWORK_CUSTODY,
        output_model=NetworkCustodyAssessment,
        events=[adk_event(function_calls=[call], function_responses=[response])],
    )
    assert {"tool_name": "custody_graph_read", "outcome": "REQUESTED"} in (
        result["execution"]["tool_invocations"]
    )
    assert {"tool_name": "custody_graph_read", "outcome": "COMPLETED"} in (
        result["execution"]["tool_invocations"]
    )


@pytest.mark.parametrize("text", [
    "not json",
    '{"lot_id":"LTC-4471"}',
    CUSTODY_JSON[:-1] + ',"unapproved":"field"}',
])
def test_invalid_structured_output_is_refused(text):
    with pytest.raises(FleetProposalError) as exc:
        run_with_fake_adk(
            agent_name="NetworkAndCustodyAgent", agent_id=AGENT_NETWORK_CUSTODY,
            output_model=NetworkCustodyAssessment, events=[adk_event(text=text)],
        )
    assert exc.value.reason_code == "INVALID_STRUCTURED_OUTPUT"


def test_model_error_is_refused_without_fallback():
    with pytest.raises(FleetProposalError) as exc:
        run_with_fake_adk(
            agent_name="NetworkAndCustodyAgent", agent_id=AGENT_NETWORK_CUSTODY,
            output_model=NetworkCustodyAssessment,
            events=[adk_event(error_code="MODEL_ERROR")],
        )
    assert exc.value.reason_code == "ADK_MODEL_ERROR"


def test_truncated_response_is_refused():
    with pytest.raises(FleetProposalError) as exc:
        run_with_fake_adk(
            agent_name="NetworkAndCustodyAgent", agent_id=AGENT_NETWORK_CUSTODY,
            output_model=NetworkCustodyAssessment,
            events=[adk_event(text='{"lot_id":"', finish_reason="MAX_TOKENS")],
        )
    assert exc.value.reason_code == "ADK_RESPONSE_INCOMPLETE"


def test_missing_run_identifier_is_refused():
    with pytest.raises(FleetProposalError) as exc:
        run_with_fake_adk(
            agent_name="NetworkAndCustodyAgent", agent_id=AGENT_NETWORK_CUSTODY,
            output_model=NetworkCustodyAssessment,
            events=[adk_event(invocation_id="")],
        )
    assert exc.value.reason_code == "ADK_RUN_IDENTIFIER_MISSING"


def test_agent_timeout_is_bounded_and_refuses():
    agent = SimpleNamespace(name="NetworkAndCustodyAgent")
    runner = MagicMock()

    async def run_async(*args, **kwargs):
        await asyncio.sleep(5)
        yield adk_event()

    runner.run_async = run_async
    session_service = MagicMock()

    async def create_session(*args, **kwargs):
        return SimpleNamespace(id="session-1")

    session_service.create_session = create_session
    with patch("google.adk.runners.Runner", return_value=runner), patch(
        "google.adk.sessions.InMemorySessionService", return_value=session_service
    ):
        with pytest.raises(FleetProposalError) as exc:
            agents.run_specialist_agent(
                agent=agent, agent_id=AGENT_NETWORK_CUSTODY, prompt="p",
                output_model=NetworkCustodyAssessment, timeout_seconds=0.05,
            )
    assert exc.value.reason_code == "ADK_TIMEOUT"


def test_upstream_exception_text_never_reaches_evidence():
    agent = SimpleNamespace(name="NetworkAndCustodyAgent")
    runner = MagicMock()

    async def run_async(*args, **kwargs):
        raise RuntimeError("sensitive recall document body")
        yield  # pragma: no cover

    runner.run_async = run_async
    session_service = MagicMock()

    async def create_session(*args, **kwargs):
        return SimpleNamespace(id="session-1")

    session_service.create_session = create_session
    with patch("google.adk.runners.Runner", return_value=runner), patch(
        "google.adk.sessions.InMemorySessionService", return_value=session_service
    ):
        with pytest.raises(FleetProposalError) as exc:
            agents.run_specialist_agent(
                agent=agent, agent_id=AGENT_NETWORK_CUSTODY, prompt="p",
                output_model=NetworkCustodyAssessment,
            )
    assert exc.value.reason_code == "ADK_INVOCATION_FAILED"
    assert "sensitive recall document body" not in str(exc.value)


def test_prompts_declare_trusted_inputs_only():
    # Custody, candidate, and partner prompts are built from normalized
    # authoritative data, so Model Armor is NOT_APPLICABLE for these hops.
    # Untrusted notice text reaches only the recall extraction agent, behind
    # the existing managed screening call.
    import inspect

    source = inspect.getsource(agents)
    assert "Model Armor is NOT_APPLICABLE" in source
    assert source.count("NOT_APPLICABLE") >= 3
