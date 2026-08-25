"""Trigger-specific orchestration paths for the Full Shelf five-agent fleet.

Each path represents a distinct sequence of specialists required for a specific
operational trigger. No agent is invoked for unrelated triggers; each path is
self-contained and deterministic.

Paths defined in AGENT_CONTRACT_V2:
1. Fleet failure: Incident Lead → Fulfillment Planning & Recovery
2. Recall: Extraction → Incident Lead → Network & Custody → Planning → Partner Ops
3. Partner callback: Model Armor → Partner Operations (no planning)
4. Daily planning: Deterministic candidates → Fulfillment Planning & Recovery
"""

from enum import Enum
from typing import Literal


class TriggerClass(str, Enum):
    """Operational trigger that determines which agents are invoked."""

    DAILY_PLANNING = "DAILY_PLANNING"
    FLEET_FAILURE = "FLEET_FAILURE"
    RECALL = "RECALL"
    PARTNER_CALLBACK = "PARTNER_CALLBACK"
    NEXT_DAY_DRAFT = "NEXT_DAY_DRAFT"


class OrchestrationPath:
    """Describes the sequence of agents for one trigger class."""

    def __init__(self, trigger: TriggerClass, agents: tuple, description: str):
        self.trigger = trigger
        self.agents = agents  # Tuple of agent IDs in order
        self.description = description


# Define the canonical trigger-specific paths as specified in Agent Contract V2
ORCHESTRATION_PATHS = {
    TriggerClass.FLEET_FAILURE: OrchestrationPath(
        TriggerClass.FLEET_FAILURE,
        ("full-shelf.incident-lead.v1", "full-shelf.fulfillment-planning-recovery.v2"),
        "Vehicle/capability failure: scope incident and select repair plan",
    ),
    TriggerClass.RECALL: OrchestrationPath(
        TriggerClass.RECALL,
        (
            "full-shelf.recall-intake-extraction.v2",
            "full-shelf.incident-lead.v1",
            "full-shelf.network-custody.v2",
            "full-shelf.fulfillment-planning-recovery.v2",
            "full-shelf.partner-operations.v2",
        ),
        "Food safety recall: extract scope, scope response, reconcile custody, plan recovery, contact partners",
    ),
    TriggerClass.PARTNER_CALLBACK: OrchestrationPath(
        TriggerClass.PARTNER_CALLBACK,
        ("full-shelf.partner-operations.v2",),
        "Authenticated partner response: interpret evidence and propose custody actions",
    ),
    TriggerClass.DAILY_PLANNING: OrchestrationPath(
        TriggerClass.DAILY_PLANNING,
        ("full-shelf.fulfillment-planning-recovery.v2",),
        "Morning planning: select daily plan from deterministic candidates",
    ),
    TriggerClass.NEXT_DAY_DRAFT: OrchestrationPath(
        TriggerClass.NEXT_DAY_DRAFT,
        ("full-shelf.fulfillment-planning-recovery.v2",),
        "Evening draft: propose next-day plan under carried-forward constraints",
    ),
}


def sequence_for_trigger(trigger: TriggerClass) -> tuple:
    """Return the agent sequence (tuple of agent IDs) for a trigger class."""
    path = ORCHESTRATION_PATHS.get(trigger)
    if not path:
        raise ValueError(f"Unknown trigger class: {trigger}")
    return path.agents


def describe_orchestration():
    """Return a human-readable description of all orchestration paths."""
    lines = ["Full Shelf Trigger-Specific Agent Orchestration:\n"]
    for trigger, path in ORCHESTRATION_PATHS.items():
        lines.append(f"  {trigger.value}: {path.description}")
        lines.append(f"    Agents: {' → '.join(path.agents)}\n")
    return "\n".join(lines)
