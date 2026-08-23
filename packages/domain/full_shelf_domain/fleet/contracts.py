"""Shared identity, trust, and schema contracts for the five-agent ADK fleet.

This module is the single source of truth for agent IDs, versions, tool IDs,
and proposal schemas. The versioned manifest and the runtime agent definitions
both derive from these constants, so a catalog entry cannot drift from an
executable definition without failing `test_fleet_catalog.py`.

Nothing here may import a ledger mutation client, a Spanner write client, a KMS
signer, or any outbound publisher. `test_fleet_isolation.py` enforces that
structurally.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


FLEET_MANIFEST_VERSION = "1.1.0"


class ComponentKind(str, Enum):
    """Truthful classification for every catalogable fleet component."""

    ADK_WORKFLOW_AGENT = "ADK_WORKFLOW_AGENT"
    ADK_LLM_AGENT = "ADK_LLM_AGENT"
    DETERMINISTIC_READ_TOOL = "DETERMINISTIC_READ_TOOL"
    DETERMINISTIC_VALIDATOR = "DETERMINISTIC_VALIDATOR"
    POLICY_GATEWAY = "POLICY_GATEWAY"


class TrustClass(str, Enum):
    """Provenance of an input reaching an agent."""

    UNTRUSTED_EXTERNAL = "UNTRUSTED_EXTERNAL"
    MODEL_ARMOR_APPROVED = "MODEL_ARMOR_APPROVED"
    TRUSTED_AUTHORITATIVE = "TRUSTED_AUTHORITATIVE"
    TRUSTED_DERIVED = "TRUSTED_DERIVED"


# --- Stable agent identity -------------------------------------------------

AGENT_INCIDENT_COORDINATOR = "full-shelf.incident-coordinator.v1"
AGENT_NETWORK_CUSTODY = "full-shelf.network-custody.v1"
AGENT_FULFILLMENT_RECOVERY = "full-shelf.fulfillment-recovery.v1"
AGENT_PARTNER_OPERATIONS = "full-shelf.partner-operations.v1"
AGENT_RECALL_EXTRACTION = "full-shelf.recall-extraction.v1"

FLEET_AGENT_IDS = (
    AGENT_INCIDENT_COORDINATOR,
    AGENT_NETWORK_CUSTODY,
    AGENT_FULFILLMENT_RECOVERY,
    AGENT_PARTNER_OPERATIONS,
    AGENT_RECALL_EXTRACTION,
)

# --- Stable read-only tool identity ----------------------------------------

TOOL_CUSTODY_GRAPH_READ = "full-shelf.tool.custody-graph-read.v1"
TOOL_CUSTODY_DEPENDENTS_READ = "full-shelf.tool.custody-dependents-read.v1"
TOOL_RECOVERY_CANDIDATES_READ = "full-shelf.tool.recovery-candidates-read.v1"
TOOL_PARTNER_STATE_READ = "full-shelf.tool.partner-state-read.v1"

# Only tools an agent actually holds are catalogued. The recovery-candidate and
# partner-state projections remain deterministic read functions used to build
# prompts; they are not ADK tools, so they are not advertised as such.
FLEET_TOOL_IDS = (
    TOOL_CUSTODY_GRAPH_READ,
    TOOL_CUSTODY_DEPENDENTS_READ,
)

# The exact model-visible ADK function name for each governed tool ID. The tool
# factories assert against this map, so a runtime name can never drift from the
# catalog. Names are unique by construction (checked in test_fleet_catalog).
TOOL_RUNTIME_NAMES = {
    TOOL_CUSTODY_GRAPH_READ: "custody_graph_read_tool",
    TOOL_CUSTODY_DEPENDENTS_READ: "custody_dependents_read_tool",
}

# Every agent's complete tool allowlist. An empty tuple is an explicit,
# catalogable statement that the agent holds no tool authority at all.
# Only the Network and Custody agent needs live tool access: custody
# investigation is genuinely exploratory, so it reads the graph and may follow
# up on a specific node. The planner and partner agents receive their complete
# bounded input directly in the prompt, so they hold no tools rather than
# carrying a catalog entry with no runtime behavior.
AGENT_TOOL_ALLOWLIST: Dict[str, tuple] = {
    AGENT_INCIDENT_COORDINATOR: (),
    AGENT_NETWORK_CUSTODY: (TOOL_CUSTODY_GRAPH_READ, TOOL_CUSTODY_DEPENDENTS_READ),
    AGENT_FULFILLMENT_RECOVERY: (),
    AGENT_PARTNER_OPERATIONS: (),
    AGENT_RECALL_EXTRACTION: (),
}

# Bounded wall-clock budget per agent. No agent may loop or retry internally;
# re-entry is owned by the existing idempotent Pub/Sub event mechanism.
AGENT_TIMEOUT_SECONDS: Dict[str, float] = {
    AGENT_INCIDENT_COORDINATOR: 90.0,
    AGENT_NETWORK_CUSTODY: 30.0,
    AGENT_FULFILLMENT_RECOVERY: 30.0,
    AGENT_PARTNER_OPERATIONS: 30.0,
    AGENT_RECALL_EXTRACTION: 30.0,
}

MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class FleetProposalError(RuntimeError):
    """Deterministic rejection of an advisory agent proposal.

    Carrying only a stable reason code keeps model text, prompts, and upstream
    exception detail out of persisted evidence.
    """

    def __init__(self, reason_code: str, agent_id: Optional[str] = None):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.agent_id = agent_id


# --- Strict agent output schemas -------------------------------------------


class NetworkCustodyAssessment(BaseModel):
    """Advisory custody reading. Every number must match deterministic tool output."""

    model_config = ConfigDict(extra="forbid")

    lot_id: str = Field(min_length=1, max_length=64)
    total_cases_in_custody: int = Field(ge=0, le=100000)
    confirmed_cases: int = Field(ge=0, le=100000)
    unconfirmed_cases: int = Field(ge=0, le=100000)
    unconfirmed_node_ids: List[str] = Field(max_length=32)
    max_path_depth: int = Field(ge=0, le=32)
    containment_assessment: Literal["FULLY_TRACED", "UNCONFIRMED_DOWNSTREAM"]
    narrative: str = Field(min_length=1, max_length=600)


class RecoverySelection(BaseModel):
    """Advisory selection of one deterministic candidate. No quantities may appear."""

    model_config = ConfigDict(extra="forbid")

    selected_candidate_id: str = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=1, max_length=600)
    cited_constraints: List[str] = Field(min_length=1, max_length=8)
    tradeoffs: str = Field(min_length=1, max_length=600)
    confidence: float = Field(ge=0.0, le=1.0)


class PartnerTemplateParameters(BaseModel):
    """The only renderable parameters, each with an authoritative source.

    Declared as explicit optional fields rather than an open string map: a
    free-form `Dict[str, str]` gives structured decoding no declared keys, so
    the model returns an empty object. Naming the fields also makes it
    impossible to express a parameter that has no authoritative binding.
    """

    model_config = ConfigDict(extra="forbid")

    partner_name: Optional[str] = None
    lot_id: Optional[str] = None
    cases: Optional[str] = None
    deadline: Optional[str] = None

    def supplied(self) -> Dict[str, str]:
        """Return only the parameters the agent actually populated."""
        return {
            name: value for name, value in self.model_dump().items()
            if value is not None
        }


class PartnerCommunication(BaseModel):
    """Advisory template selection. Rendering is deterministic and external."""

    model_config = ConfigDict(extra="forbid")

    partner_id: str = Field(min_length=1, max_length=64)
    template_id: str = Field(min_length=1, max_length=64)
    escalation_level: Literal["ROUTINE", "PRIORITY", "URGENT"]
    template_parameters: PartnerTemplateParameters = Field(
        default_factory=PartnerTemplateParameters
    )
    rationale: str = Field(min_length=1, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)


class FleetProposal(BaseModel):
    """Assembled advisory output of one coordinator run. Never authoritative."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["PROPOSED", "MANUAL_REVIEW_REQUIRED"]
    incident_id: str
    lot_id: str
    reason_code: Optional[str] = None
    extraction: Optional[Dict[str, Any]] = None
    custody: Optional[NetworkCustodyAssessment] = None
    recovery: Optional[RecoverySelection] = None
    partner: Optional[PartnerCommunication] = None
    delegation_trace: List[Dict[str, Any]] = Field(default_factory=list)
    coordinator_session_id: Optional[str] = None
    coordination_run_id: Optional[str] = None
    proposal_hash: Optional[str] = None


# --- Deterministic, versioned partner templates ----------------------------
# Rendering happens outside the fleet. The agent may only name a template ID
# and supply parameters that the renderer will validate.

# Every parameter of every template must have an authoritative source in
# `partner_state_read` output. `pickup_window` was removed because no
# authoritative source for it exists; a model may not invent a delivery window.
PARTNER_TEMPLATE_IDS = {
    "partner.pickup-request.v1": ("partner_name", "lot_id", "cases"),
    "partner.acknowledgment-request.v1": ("partner_name", "lot_id", "cases", "deadline"),
    "partner.shortfall-notice.v1": ("partner_name", "lot_id", "cases"),
}

# Deterministic escalation policy. The agent reports an escalation level, but
# the validator recomputes it from trusted partner state and rejects any
# disagreement, so escalation is never model-authored.
def deterministic_escalation_level(partner_state: dict) -> str:
    """Derive the only admissible escalation level from trusted partner state."""
    if partner_state.get("acknowledgment_status") != "UNCONFIRMED":
        return "ROUTINE"
    return "URGENT" if partner_state.get("deadline") else "PRIORITY"

# Confidence at or below this value is refused rather than acted upon.
PARTNER_MIN_CONFIDENCE = 0.5
RECOVERY_MIN_CONFIDENCE = 0.5
