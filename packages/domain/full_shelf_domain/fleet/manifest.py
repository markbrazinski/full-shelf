"""Internal versioned fleet manifest, derived from executable definitions.

This is NOT a managed Agent Registry, Agent Card publication, or Tool Gateway
manifest. It is a local catalog whose every entry is computed from the same
constants the runtime agents use, so a catalog claim cannot drift from an
executable definition. `test_fleet_catalog.py` re-derives the manifest and fails
if any entry, tool allowlist, schema field set, or role gate diverges.

Classification: STRUCTURALLY_VERIFIED locally. Live agent invocation, managed
registry coverage, and managed observability remain NOT_PROVEN until an
independent auditor observes a managed deployment.
"""

from typing import Any, Dict, List

from .agents import MODEL_ID
from .contracts import (
    AGENT_FULFILLMENT_RECOVERY,
    TOOL_RUNTIME_NAMES,
    AGENT_INCIDENT_COORDINATOR,
    AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
    AGENT_RECALL_EXTRACTION,
    AGENT_TIMEOUT_SECONDS,
    AGENT_TOOL_ALLOWLIST,
    FLEET_MANIFEST_VERSION,
    PARTNER_TEMPLATE_IDS,
    TOOL_CUSTODY_DEPENDENTS_READ,
    TOOL_CUSTODY_GRAPH_READ,
    ComponentKind,
    NetworkCustodyAssessment,
    PartnerCommunication,
    RecoverySelection,
    TrustClass,
)
from .tools import CANDIDATE_POLICY_ID, CANDIDATE_POLICY_ORDERINGS

# The ledger role each agent's advice may inform. The agent never holds the
# role; the orchestrator submits under it after deterministic revalidation.
AGENT_INFORMED_LEDGER_ROLE = {
    AGENT_INCIDENT_COORDINATOR: "INCIDENT_COORDINATOR",
    AGENT_NETWORK_CUSTODY: "INCIDENT_COORDINATOR",
    AGENT_FULFILLMENT_RECOVERY: "FULFILLMENT_RECOVERY_PLANNER",
    AGENT_PARTNER_OPERATIONS: "INCIDENT_COORDINATOR",
    AGENT_RECALL_EXTRACTION: "INCIDENT_COORDINATOR",
}

_AGENT_SPECS = {
    AGENT_INCIDENT_COORDINATOR: {
        "product_role": "Incident Coordinator",
        "runtime_name": "IncidentCoordinatorAgent",
        "kind": ComponentKind.ADK_WORKFLOW_AGENT,
        "uses_gemini": False,
        "input_trust": [TrustClass.TRUSTED_DERIVED],
        "output_schema": "CoordinationPayload",
        "output_contract": (
            "Emits a JSON coordination payload (status, reason_code, "
            "delegation_trace, accepted_agent_ids). FleetProposal is assembled "
            "deterministically by run_fleet from the accepted specialist "
            "outputs; the coordinator agent does not emit it."
        ),
        "instruction_source": "full_shelf_domain.fleet.coordinator:IncidentCoordinatorAgent",
        "failure_behavior": "MANUAL_REVIEW_REQUIRED",
    },
    AGENT_NETWORK_CUSTODY: {
        "product_role": "Network and Custody",
        "runtime_name": "NetworkAndCustodyAgent",
        "kind": ComponentKind.ADK_LLM_AGENT,
        "uses_gemini": True,
        "input_trust": [TrustClass.TRUSTED_AUTHORITATIVE],
        "output_schema": NetworkCustodyAssessment.__name__,
        "instruction_source": "full_shelf_domain.fleet.agents:NETWORK_CUSTODY_INSTRUCTION",
        "failure_behavior": "MANUAL_REVIEW_REQUIRED",
    },
    AGENT_FULFILLMENT_RECOVERY: {
        "product_role": "Fulfillment and Recovery Planner",
        "runtime_name": "FulfillmentAndRecoveryPlannerAgent",
        "kind": ComponentKind.ADK_LLM_AGENT,
        "uses_gemini": True,
        "input_trust": [TrustClass.TRUSTED_DERIVED],
        "output_schema": RecoverySelection.__name__,
        "instruction_source": "full_shelf_domain.fleet.agents:FULFILLMENT_RECOVERY_INSTRUCTION",
        "failure_behavior": "MANUAL_REVIEW_REQUIRED",
    },
    AGENT_PARTNER_OPERATIONS: {
        "product_role": "Partner Operations",
        "runtime_name": "PartnerOperationsAgent",
        "kind": ComponentKind.ADK_LLM_AGENT,
        "uses_gemini": True,
        "input_trust": [TrustClass.TRUSTED_AUTHORITATIVE],
        "output_schema": PartnerCommunication.__name__,
        "instruction_source": "full_shelf_domain.fleet.agents:PARTNER_OPERATIONS_INSTRUCTION",
        "failure_behavior": "MANUAL_REVIEW_REQUIRED",
    },
    AGENT_RECALL_EXTRACTION: {
        "product_role": "Recall Extraction",
        "runtime_name": "RecallExtractionAgent",
        "kind": ComponentKind.ADK_LLM_AGENT,
        "uses_gemini": True,
        "input_trust": [TrustClass.MODEL_ARMOR_APPROVED],
        "output_schema": "RecallExtractionSchema",
        "instruction_source": "full_shelf_domain.fleet.agents:RECALL_EXTRACTION_INSTRUCTION",
        "failure_behavior": "MANUAL_REVIEW_REQUIRED",
    },
}

_TOOL_SPECS = {
    TOOL_CUSTODY_GRAPH_READ: {
        "kind": ComponentKind.DETERMINISTIC_READ_TOOL,
        "implementation": "full_shelf_domain.fleet.tools:custody_graph_read",
        "reads": "Spanner Graph custody reconstruction (already executed)",
    },
    TOOL_CUSTODY_DEPENDENTS_READ: {
        "kind": ComponentKind.DETERMINISTIC_READ_TOOL,
        "implementation": "full_shelf_domain.fleet.tools:custody_dependents_read",
        "reads": "Downstream dependents of one custody node",
    },
}

_VALIDATOR_SPECS = {
    "full-shelf.validator.custody-reconciliation.v1": {
        "kind": ComponentKind.DETERMINISTIC_VALIDATOR,
        "implementation": "full_shelf_domain.fleet.validation:validate_custody_assessment",
        "enforces": "Every agent-reported count equals the Spanner Graph result",
    },
    "full-shelf.validator.recovery-selection.v1": {
        "kind": ComponentKind.DETERMINISTIC_VALIDATOR,
        "implementation": "full_shelf_domain.fleet.validation:validate_recovery_selection",
        "enforces": "Only an existing candidate_id resolves; contents come from code",
    },
    "full-shelf.validator.partner-communication.v1": {
        "kind": ComponentKind.DETERMINISTIC_VALIDATOR,
        "implementation": "full_shelf_domain.fleet.validation:validate_partner_communication",
        "enforces": "Approved template IDs and authoritative parameters only",
    },
    "full-shelf.gateway.plan-ledger.v1": {
        "kind": ComponentKind.POLICY_GATEWAY,
        "implementation": "apps/plan-ledger/src/main.py",
        "enforces": (
            "Exclusive authoritative mutation authority; identity, policy, "
            "idempotency, KMS approval binding, and zero-mutation refusal"
        ),
    },
}


def build_manifest() -> Dict[str, Any]:
    """Derive the complete fleet manifest from executable definitions."""
    from .coordinator import GOVERNED_SEQUENCE

    agents: List[Dict[str, Any]] = []
    for agent_id in _AGENT_SPECS:
        spec = _AGENT_SPECS[agent_id]
        agents.append({
            "agent_id": agent_id,
            "version": agent_id.rsplit(".", 1)[-1],
            "product_role": spec["product_role"],
            "runtime_name": spec["runtime_name"],
            "component_kind": spec["kind"].value,
            "framework": "google-adk",
            "uses_gemini": spec["uses_gemini"],
            "model_id": MODEL_ID if spec["uses_gemini"] else None,
            "input_trust_classes": [t.value for t in spec["input_trust"]],
            "output_schema": spec["output_schema"],
            "output_contract": spec.get("output_contract"),
            "instruction_source": spec["instruction_source"],
            "tool_allowlist": list(AGENT_TOOL_ALLOWLIST[agent_id]),
            "timeout_seconds": AGENT_TIMEOUT_SECONDS[agent_id],
            "failure_behavior": spec["failure_behavior"],
            "mutation_authority": "NONE",
            "informed_ledger_role": AGENT_INFORMED_LEDGER_ROLE[agent_id],
        })

    tools = [
        {
            "tool_id": tool_id,
            "runtime_tool_name": TOOL_RUNTIME_NAMES[tool_id],
            "component_kind": spec["kind"].value,
            "implementation": spec["implementation"],
            "reads": spec["reads"],
            "access": "READ_ONLY",
            "mutation_authority": "NONE",
            "granted_to": sorted(
                agent_id for agent_id, allowed in AGENT_TOOL_ALLOWLIST.items()
                if tool_id in allowed
            ),
        }
        for tool_id, spec in _TOOL_SPECS.items()
        if any(tool_id in allowed for allowed in AGENT_TOOL_ALLOWLIST.values())
    ]

    governance = [
        {
            "component_id": component_id,
            "component_kind": spec["kind"].value,
            "implementation": spec["implementation"],
            "enforces": spec["enforces"],
        }
        for component_id, spec in _VALIDATOR_SPECS.items()
    ]

    return {
        "manifest_version": FLEET_MANIFEST_VERSION,
        "classification": "STRUCTURALLY_VERIFIED",
        "scope": "Internal local catalog derived from executable definitions",
        "topology": {
            "kind": "SEPARATE_RUNNER_COORDINATION",
            "description": (
                "The coordinator runs under its own ADK Runner and drives each "
                "specialist through that specialist's own Runner and own ADK "
                "session. Specialists are declared sub_agents of the "
                "coordinator, but each specialist invocation is a distinct ADK "
                "invocation with its own run and session identifiers."
            ),
            "specialists_are_adk_children_of_coordinator_invocation": False,
            "evidence_fields": [
                "coordinator_agent_id", "coordination_run_id",
                "specialist_run_id", "specialist_session_id",
            ],
        },
        "not_claimed": [
            "Managed Agent Registry",
            "Managed Agent Identity",
            "Managed Agent Gateway",
            "Managed Agent Runtime/Sessions",
            "Managed Memory Bank",
            "Managed Agent Observability",
            "Published Agent Cards or Tool Gateway Manifest",
        ],
        "agent_count": len(agents),
        "agents": agents,
        "tools": tools,
        "governance": governance,
        "partner_templates": sorted(PARTNER_TEMPLATE_IDS),
        "governed_sequence": list(GOVERNED_SEQUENCE),
        "recovery_candidate_scope": {
            "policy_id": CANDIDATE_POLICY_ID,
            "scope": "BOUNDED_ADMISSIBLE_CANDIDATE_SET",
            "orderings": list(CANDIDATE_POLICY_ORDERINGS),
            "limitation": (
                "This is the bounded admissible candidate set produced by the "
                "deterministic lot-ordering policy, not an exhaustive "
                "enumeration of every feasible allocation."
            ),
        },
        "mutation_authority_summary": (
            "No agent and no agent tool holds mutation authority. The private "
            "plan-ledger service remains the exclusive authoritative writer."
        ),
    }
