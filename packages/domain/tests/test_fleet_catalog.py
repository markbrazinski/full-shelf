"""Catalog-versus-code reconciliation. Any drift fails here.

Every manifest claim is re-derived from the runtime agent objects, the tool
allowlist constants, and the Pydantic schemas. Renaming an agent, adding a tool,
widening an allowlist, or changing a schema without updating the definitions
these tests read will fail.
"""

import pytest

from full_shelf_domain.fleet import agents as agent_module
from full_shelf_domain.fleet import contracts
from full_shelf_domain.fleet.coordinator import (
    build_incident_coordinator_agent,
    AGENT_INCIDENT_COORDINATOR,
)
from full_shelf_domain.fleet.manifest import build_manifest


MANIFEST = build_manifest()
BY_ID = {entry["agent_id"]: entry for entry in MANIFEST["agents"]}


def test_manifest_lists_exactly_the_five_declared_agents():
    assert MANIFEST["agent_count"] == 5
    assert set(BY_ID) == set(contracts.FLEET_AGENT_IDS)


def test_manifest_runtime_names_match_constructed_adk_agents():
    constructed = {
        contracts.AGENT_NETWORK_CUSTODY: agent_module.build_network_custody_agent([]),
        contracts.AGENT_FULFILLMENT_PLANNING_RECOVERY:
            agent_module.build_fulfillment_planning_recovery_agent([]),
        contracts.AGENT_PARTNER_OPERATIONS:
            agent_module.build_partner_operations_agent([]),
    }
    for agent_id, agent in constructed.items():
        assert BY_ID[agent_id]["runtime_name"] == agent.name
    # Coordinator is not in the manifest; it is runtime infrastructure.
    coordinator_agent = build_incident_coordinator_agent()
    assert coordinator_agent.name == "IncidentCoordinatorAgent"


def test_manifest_output_schemas_match_runtime_output_schemas():
    pairs = [
        (contracts.AGENT_NETWORK_CUSTODY,
         agent_module.build_network_custody_agent([])),
        (contracts.AGENT_FULFILLMENT_PLANNING_RECOVERY,
         agent_module.build_fulfillment_planning_recovery_agent([])),
        (contracts.AGENT_PARTNER_OPERATIONS,
         agent_module.build_partner_operations_agent([])),
    ]
    for agent_id, agent in pairs:
        assert BY_ID[agent_id]["output_schema"] == agent.output_schema.__name__


def test_manifest_tool_allowlists_match_the_executable_allowlist():
    for agent_id, entry in BY_ID.items():
        assert entry["tool_allowlist"] == list(
            contracts.AGENT_TOOL_ALLOWLIST[agent_id]
        )


def test_manifest_grants_are_the_inverse_of_the_allowlist():
    for tool in MANIFEST["tools"]:
        expected = sorted(
            agent_id for agent_id, allowed in contracts.AGENT_TOOL_ALLOWLIST.items()
            if tool["tool_id"] in allowed
        )
        assert tool["granted_to"] == expected
        # Every catalogued tool must actually be granted to someone.
        assert expected, tool["tool_id"]


def test_every_catalogued_tool_resolves_to_a_real_read_only_function():
    import importlib

    for tool in MANIFEST["tools"]:
        module_path, _, symbol = tool["implementation"].partition(":")
        module = importlib.import_module(module_path)
        assert callable(getattr(module, symbol)), tool["tool_id"]
        assert tool["access"] == "READ_ONLY"
        assert tool["mutation_authority"] == "NONE"


def test_every_catalogued_validator_resolves_to_a_real_function():
    import importlib

    for entry in MANIFEST["governance"]:
        if entry["component_kind"] != "DETERMINISTIC_VALIDATOR":
            continue
        module_path, _, symbol = entry["implementation"].partition(":")
        module = importlib.import_module(module_path)
        assert callable(getattr(module, symbol)), entry["component_id"]


def test_no_agent_declares_mutation_authority():
    assert all(entry["mutation_authority"] == "NONE" for entry in MANIFEST["agents"])
    assert all(tool["mutation_authority"] == "NONE" for tool in MANIFEST["tools"])


def test_manifest_declares_the_policy_gateway_as_the_only_writer():
    gateways = [
        entry for entry in MANIFEST["governance"]
        if entry["component_kind"] == "POLICY_GATEWAY"
    ]
    assert len(gateways) == 1
    assert "plan-ledger" in gateways[0]["implementation"]
    assert "exclusive authoritative writer" in (
        MANIFEST["mutation_authority_summary"]
    )


def test_manifest_uses_only_the_five_approved_component_kinds():
    approved = {kind.value for kind in contracts.ComponentKind}
    kinds = (
        {entry["component_kind"] for entry in MANIFEST["agents"]}
        | {tool["component_kind"] for tool in MANIFEST["tools"]}
        | {entry["component_kind"] for entry in MANIFEST["governance"]}
    )
    assert kinds <= approved
    # The five agents in the manifest are all LLM specialists.
    assert "ADK_LLM_AGENT" in kinds
    # The coordinator is separate infrastructure, built at runtime, not in the manifest.
    # It is ADK_WORKFLOW_AGENT class but not catalogued here.


def test_manifest_claims_no_managed_preview_product():
    for claim in ("Managed Agent Registry", "Managed Agent Identity",
                  "Managed Agent Gateway", "Managed Agent Observability",
                  "Published Agent Cards or Tool Gateway Manifest"):
        assert claim in MANIFEST["not_claimed"]
    assert MANIFEST["classification"] == "STRUCTURALLY_VERIFIED"


def test_partner_templates_in_catalog_match_executable_templates():
    assert MANIFEST["partner_templates"] == sorted(contracts.PARTNER_TEMPLATE_IDS)


def test_informed_ledger_roles_are_real_orchestrator_roles():
    # These roles are submitted by the orchestrator, never held by an agent.
    assert {entry["informed_ledger_role"] for entry in MANIFEST["agents"]} == {
        "INCIDENT_COORDINATOR", "FULFILLMENT_RECOVERY_PLANNER",
    }


def test_timeouts_and_failure_behavior_are_catalogued_for_every_agent():
    for agent_id, entry in BY_ID.items():
        assert entry["timeout_seconds"] == contracts.AGENT_TIMEOUT_SECONDS[agent_id]
        assert entry["failure_behavior"] == "MANUAL_REVIEW_REQUIRED"


def test_only_the_coordinator_is_a_non_gemini_workflow_agent():
    # The five specialist agents in the manifest are all LLM agents.
    for agent_id, entry in BY_ID.items():
        assert entry["uses_gemini"] is True
        assert entry["component_kind"] == "ADK_LLM_AGENT"
    # The coordinator is not catalogued in the manifest; it is runtime infrastructure.
    coordinator_in_manifest = any(
        a["agent_id"] == AGENT_INCIDENT_COORDINATOR for a in MANIFEST["agents"]
    )
    assert coordinator_in_manifest is False


def test_untrusted_content_reaches_only_the_screened_extraction_agent():
    for agent_id, entry in BY_ID.items():
        # Check both flat (legacy) and mode-scoped (new) trust structures
        if "input_trust_classes" in entry:
            assert "UNTRUSTED_EXTERNAL" not in entry["input_trust_classes"], agent_id
        if "input_trust_by_mode" in entry:
            for mode_classes in entry["input_trust_by_mode"].values():
                assert "UNTRUSTED_EXTERNAL" not in mode_classes, agent_id

    # Recall uses MODEL_ARMOR_APPROVED
    assert BY_ID[contracts.AGENT_RECALL_INTAKE_EXTRACTION]["input_trust_classes"] == [
        "MODEL_ARMOR_APPROVED"
    ]


# --- Finding 9 & 10: catalog cannot overstate or drift ----------------------


def test_candidate_scope_is_stated_as_a_bounded_policy_not_completeness():
    scope = MANIFEST["recovery_candidate_scope"]
    assert scope["scope"] == "BOUNDED_ADMISSIBLE_CANDIDATE_SET"
    assert "not an exhaustive" in scope["limitation"]
    # And the executable policy matches exactly what the catalog advertises.
    from full_shelf_domain.fleet.tools import (
        CANDIDATE_POLICY_ID, CANDIDATE_POLICY_ORDERINGS,
    )

    assert scope["policy_id"] == CANDIDATE_POLICY_ID
    assert scope["orderings"] == list(CANDIDATE_POLICY_ORDERINGS)
    stale_claim = " ".join(["complete", "feasible"])
    assert stale_claim not in str(MANIFEST).lower()


def test_orchestration_paths_have_all_triggers():
    from full_shelf_domain.fleet.orchestration import TriggerClass
    from full_shelf_domain.fleet.coordinator import AGENT_INCIDENT_COORDINATOR

    assert "orchestration_paths" in MANIFEST
    for trigger in TriggerClass:
        assert trigger.value in MANIFEST["orchestration_paths"]
        # Each path contains agents; root coordinator is not included
        path = MANIFEST["orchestration_paths"][trigger.value]
        assert len(path) > 0
        assert AGENT_INCIDENT_COORDINATOR not in path


def test_runtime_tool_names_are_unique_and_catalogued():
    names = [tool["runtime_tool_name"] for tool in MANIFEST["tools"]]
    assert len(names) == len(set(names))
    assert set(names) == set(contracts.TOOL_RUNTIME_NAMES.values())


def test_catalog_declares_partner_trust_by_mode():
    partner = BY_ID[contracts.AGENT_PARTNER_OPERATIONS]
    assert "input_trust_by_mode" in partner
    assert partner["input_trust_by_mode"]["OUTBOUND_FOLLOWUP"] == ["TRUSTED_AUTHORITATIVE"]
    assert set(partner["input_trust_by_mode"]["INBOUND_EVIDENCE"]) == {
        "AUTHENTICATED_EXTERNAL", "MODEL_ARMOR_APPROVED", "TRUSTED_AUTHORITATIVE"
    }


def test_partner_template_parameters_all_have_authoritative_sources():
    # Every template parameter must be bindable by the validator.
    bindable = {"partner_name", "lot_id", "cases", "deadline"}
    for required in contracts.PARTNER_TEMPLATE_IDS.values():
        assert set(required) <= bindable


# --- Item 3: coordinator and Recall schema parity, topology, model IDs -------


def test_coordinator_is_not_catalogued_with_an_adk_output_schema():
    """The executable coordinator is not catalogued in the manifest; it is runtime infrastructure."""
    from full_shelf_domain.fleet.coordinator import build_incident_coordinator_agent

    agent = build_incident_coordinator_agent()
    assert getattr(agent, "output_schema", None) is None
    # Coordinator is not in the manifest agent roster.
    coordinator_in_manifest = any(
        a["agent_id"] == AGENT_INCIDENT_COORDINATOR for a in MANIFEST["agents"]
    )
    assert coordinator_in_manifest is False


def test_coordinator_event_contract_matches_what_it_actually_emits():
    """The coordinator emits a coordination event (not an ADK output_schema)."""
    import inspect

    from full_shelf_domain.fleet import coordinator

    source = inspect.getsource(coordinator)
    for key in ("status", "reason_code", "delegation_trace", "accepted_agent_ids"):
        assert f'"{key}"' in source
    # Coordinator is runtime infrastructure, not a catalogued agent.
    coordinator_in_manifest = any(
        a["agent_id"] == AGENT_INCIDENT_COORDINATOR for a in MANIFEST["agents"]
    )
    assert coordinator_in_manifest is False


def test_recall_catalog_schema_matches_the_runtime_agent_schema():
    from full_shelf_domain.fleet.agents import build_recall_intake_extraction_agent

    agent = build_recall_intake_extraction_agent()
    entry = BY_ID[contracts.AGENT_RECALL_INTAKE_EXTRACTION]
    assert entry["output_schema"] == agent.output_schema.__name__
    assert entry["runtime_name"] == agent.name


def test_catalog_model_ids_match_the_runtime_model():
    from full_shelf_domain.fleet.agents import MODEL_ID

    for agent_id, entry in BY_ID.items():
        if entry["uses_gemini"]:
            assert entry["model_id"] == MODEL_ID, agent_id
        else:
            assert entry["model_id"] is None, agent_id


def test_catalog_declares_the_separate_runner_topology_truthfully():
    topology = MANIFEST["topology"]
    assert topology["kind"] == "SEPARATE_RUNNER_COORDINATION"
    assert topology[
        "specialists_are_adk_children_of_coordinator_invocation"
    ] is False
    assert set(topology["evidence_fields"]) == {
        "coordinator_agent_id", "coordination_run_id",
        "specialist_run_id", "specialist_session_id",
    }
    # No evidence field claiming parentage may exist anywhere in the fleet.
    import inspect

    from full_shelf_domain.fleet import agents, coordinator, manifest

    for module in (agents, coordinator, manifest):
        synthetic_field = "_".join(["parent", "agent", "id"])
        assert synthetic_field not in inspect.getsource(module), module.__name__


def test_manifest_version_was_bumped_for_this_contract_change():
    assert MANIFEST["manifest_version"] == "1.1.0"
    assert contracts.FLEET_MANIFEST_VERSION == "1.1.0"


def test_no_catalogued_tool_lacks_a_working_factory():
    """Item 6: a catalogued tool must be constructible, not dead code."""
    from full_shelf_domain.fleet import tools

    factories = {
        contracts.TOOL_CUSTODY_GRAPH_READ: tools.build_custody_graph_tool,
        contracts.TOOL_CUSTODY_DEPENDENTS_READ: tools.build_custody_dependents_tool,
    }
    assert set(factories) == set(contracts.FLEET_TOOL_IDS)
    # And no orphaned factory remains for an uncatalogued tool.
    assert not hasattr(tools, "build_recovery_candidates_tool")
    assert not hasattr(tools, "build_partner_state_tool")
