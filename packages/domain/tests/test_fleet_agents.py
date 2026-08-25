"""Definition-level boundary tests for the five concrete ADK agents.

These assert the constructed ADK objects: class, name, schema, transfer flags,
and the coordinator's empty tool set. Execution behavior is proven separately in
`test_fleet_runtime.py`, which runs the REAL ADK Runner with only the Gemini
network call scripted. No test in this repository mocks the ADK Runner.
"""

import pytest

from full_shelf_domain.fleet import agents, contracts
from full_shelf_domain.fleet.contracts import (
    AGENT_FULFILLMENT_PLANNING_RECOVERY,
    AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
    FleetProposalError,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
)


# --- Concrete agent definitions --------------------------------------------


def test_five_concrete_agent_ids_are_declared():
    assert len(contracts.FLEET_AGENT_IDS) == 5
    assert contracts.FLEET_AGENT_IDS == (
        "full-shelf.fulfillment-planning-recovery.v2",
        "full-shelf.incident-lead.v1",
        "full-shelf.recall-intake-extraction.v2",
        "full-shelf.network-custody.v2",
        "full-shelf.partner-operations.v2",
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
        (agents.build_fulfillment_planning_recovery_agent,
         "FulfillmentPlanningRecoveryAgent", RecoverySelection),
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
    for forbidden in ("execute_ledger_command", "post_to_plan_ledger",
                      "LedgerExecutor", "PLAN_LEDGER_URL"):
        assert forbidden not in source


def test_no_test_in_this_repository_mocks_the_adk_runner():
    """Finding 6: fake-Runner tests are not runtime evidence and must not return."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in root.glob("**/tests/test_*.py"):
        if ".venv" in str(path) or path.name == pathlib.Path(__file__).name:
            continue
        text = path.read_text()
        if 'patch("google.adk.runners.Runner"' in text or (
            "patch.object(Runner" in text
        ):
            offenders.append(path.name)
    assert offenders == [], f"ADK Runner is mocked in: {offenders}"
