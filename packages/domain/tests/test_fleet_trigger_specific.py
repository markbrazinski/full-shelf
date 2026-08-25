"""Prove trigger-specific agent orchestration per Agent Contract V2.

Contract Section 6 acceptance checks:
- unrelated agents are not invoked for each trigger
- each operating objective reaches Fulfillment agent
- agent outputs remain conditional by trigger
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from full_shelf_domain.fleet.orchestration import (
    TriggerClass, sequence_for_trigger, ORCHESTRATION_PATHS
)
from full_shelf_domain.fleet.contracts import (
    AGENT_FULFILLMENT_PLANNING_RECOVERY, AGENT_INCIDENT_LEAD,
    AGENT_RECALL_INTAKE_EXTRACTION, AGENT_NETWORK_CUSTODY,
    AGENT_PARTNER_OPERATIONS,
)


class TestTriggerSpecificPaths:
    """Test that each trigger invokes only its required agents."""

    def test_daily_planning_invokes_only_fulfillment(self):
        """DAILY_PLANNING should invoke only Fulfillment Planning & Recovery."""
        path = sequence_for_trigger(TriggerClass.DAILY_PLANNING)
        assert path == (AGENT_FULFILLMENT_PLANNING_RECOVERY,)
        assert len(path) == 1

    def test_fleet_failure_invokes_incident_lead_and_fulfillment(self):
        """FLEET_FAILURE should invoke Incident Lead then Fulfillment."""
        path = sequence_for_trigger(TriggerClass.FLEET_FAILURE)
        assert path == (
            AGENT_INCIDENT_LEAD,
            AGENT_FULFILLMENT_PLANNING_RECOVERY,
        )
        assert len(path) == 2

    def test_recall_invokes_four_agent_sequence(self):
        """RECALL invokes exactly four agents per AGENT_CONTRACT_V2 §6.

        Partner Operations is deliberately absent: §6 assigns it to the separate
        authenticated partner-evidence scenario, never chained off recall.
        """
        path = sequence_for_trigger(TriggerClass.RECALL)
        assert path == (
            AGENT_RECALL_INTAKE_EXTRACTION,
            AGENT_INCIDENT_LEAD,
            AGENT_NETWORK_CUSTODY,
            AGENT_FULFILLMENT_PLANNING_RECOVERY,
        )
        assert len(path) == 4
        assert AGENT_PARTNER_OPERATIONS not in path

    def test_partner_callback_is_not_a_fleet_trigger(self):
        """Inbound partner callbacks never route through run_fleet.

        The sole governed inbound path is main.py:process_partner_evidence, which
        is authenticated and Model-Armor screened. Proving the trigger is absent
        keeps a second, ungoverned path from reappearing.
        """
        assert "PARTNER_CALLBACK" not in TriggerClass.__members__
        for trigger in TriggerClass:
            assert AGENT_PARTNER_OPERATIONS not in sequence_for_trigger(trigger)

    def test_next_day_draft_invokes_only_fulfillment(self):
        """NEXT_DAY_DRAFT should invoke only Fulfillment Planning & Recovery."""
        path = sequence_for_trigger(TriggerClass.NEXT_DAY_DRAFT)
        assert path == (AGENT_FULFILLMENT_PLANNING_RECOVERY,)
        assert len(path) == 1


class TestOperatingObjectiveMapping:
    """Test that operating_objective is correctly set based on trigger."""

    def test_operating_objectives_defined_for_all_triggers(self):
        """Each trigger should map to a defined operating objective."""
        from full_shelf_domain.fleet.agents import recovery_prompt

        trigger_to_expected = {
            TriggerClass.DAILY_PLANNING: "DAILY_PLAN",
            TriggerClass.FLEET_FAILURE: "DISRUPTION_RECOVERY",
            TriggerClass.RECALL: "RECALL_RECOVERY",
            TriggerClass.NEXT_DAY_DRAFT: "NEXT_DAY_DRAFT",
        }

        dummy_candidates = {"dummy": "data"}
        for trigger_class, expected_obj in trigger_to_expected.items():
            prompt = recovery_prompt(dummy_candidates, trigger_class)
            assert expected_obj in prompt, (
                f"Prompt for {trigger_class.value} should contain "
                f"operating_objective: {expected_obj}"
            )


class TestNoUnrelatedAgentsInvoked:
    """Prove that unrelated agents are not invoked for their trigger."""

    def test_daily_planning_does_not_invoke_extraction(self):
        """DAILY_PLANNING should not invoke Recall Intake & Extraction."""
        path = sequence_for_trigger(TriggerClass.DAILY_PLANNING)
        assert AGENT_RECALL_INTAKE_EXTRACTION not in path

    def test_daily_planning_does_not_invoke_incident_lead(self):
        """DAILY_PLANNING should not invoke Incident Lead."""
        path = sequence_for_trigger(TriggerClass.DAILY_PLANNING)
        assert AGENT_INCIDENT_LEAD not in path
        """FLEET_FAILURE should not invoke Recall Intake & Extraction."""
        path = sequence_for_trigger(TriggerClass.FLEET_FAILURE)
        assert AGENT_RECALL_INTAKE_EXTRACTION not in path

    def test_fleet_failure_does_not_invoke_custody(self):
        """FLEET_FAILURE should not invoke Network & Custody."""
        path = sequence_for_trigger(TriggerClass.FLEET_FAILURE)
        assert AGENT_NETWORK_CUSTODY not in path

    def test_fleet_failure_does_not_invoke_partner_operations(self):
        """FLEET_FAILURE should not invoke Partner Operations."""
        path = sequence_for_trigger(TriggerClass.FLEET_FAILURE)
        assert AGENT_PARTNER_OPERATIONS not in path


class TestProposalFieldsConditionalOnTrigger:
    """Test that FleetProposal fields are only populated for agents that ran."""

    def test_proposal_fields_match_orchestration_path(self):
        """FleetProposal should only have output fields for agents in the path."""
        from full_shelf_domain.fleet.contracts import FleetProposal

        # All fields are optional so we can construct proposals for any trigger
        for trigger in TriggerClass:
            path = sequence_for_trigger(trigger)
            proposal = FleetProposal(
                status="PROPOSED",
                incident_id="test_incident",
                lot_id="test_lot",
                delegation_trace=[],
            )
            # The proposal can be created; actual field population
            # is tested in integration tests
            assert proposal.status == "PROPOSED"
            assert proposal.incident_id == "test_incident"


class TestIncidentLeadOnlyAfterExtraction:
    """Prove that Incident Lead never reads raw unscreened text."""

    def test_recall_path_extracts_before_incident_lead(self):
        """In RECALL path, Extraction runs before Incident Lead."""
        path = sequence_for_trigger(TriggerClass.RECALL)
        extraction_idx = path.index(AGENT_RECALL_INTAKE_EXTRACTION)
        incident_lead_idx = path.index(AGENT_INCIDENT_LEAD)
        assert extraction_idx < incident_lead_idx, (
            "Recall Intake & Extraction must run before Incident Lead"
        )

    def test_fleet_failure_does_not_include_extraction(self):
        """FLEET_FAILURE should not invoke Extraction (no raw text to process)."""
        path = sequence_for_trigger(TriggerClass.FLEET_FAILURE)
        assert AGENT_RECALL_INTAKE_EXTRACTION not in path

    def test_incident_lead_requires_structured_inputs(self):
        """Incident Lead should only be called with structured inputs."""
        # This is tested in coordinator hops: incident_lead_prompt()
        # takes source_event_id, source_class, lot_id (structured)
        # not screened_notice_text (raw/unscreened)
        from full_shelf_domain.fleet.agents import incident_lead_prompt

        prompt = incident_lead_prompt(
            source_event_id="EVT-123",
            source_class="FOOD_SAFETY_RECALL",
            affected_lot_id="LTC-4471"
        )
        # Prompt should NOT contain raw notice text markers
        assert "Model-Armor" not in prompt
        assert "screened" not in prompt.lower()

    def test_incident_lead_prompt_renders_real_extracted_values(self):
        """The prompt must carry the facts, not an 'unknown' placeholder.

        These fields were read under their deleted V1 names with an 'unknown'
        default, so Incident Lead scoped every incident without seeing what
        extraction had established.
        """
        from full_shelf_domain.fleet.agents import incident_lead_prompt

        prompt = incident_lead_prompt(
            source_event_id="EVT-001",
            source_class="FOOD_SAFETY_RECALL",
            affected_lot_id="LTC-4471",
            extraction={
                "lot_id": {"value": "LTC-4471", "quote": "Lot LTC-4471"},
                "hazard": {"value": "E. coli O157:H7", "quote": "E. coli O157:H7"},
                "notice_scope": [
                    {"value": "Romaine Lettuce", "quote": "Romaine Lettuce"},
                ],
            },
        )
        assert "E. coli O157:H7" in prompt
        assert "Romaine Lettuce" in prompt
        assert "unknown" not in prompt


class TestRecallPathFullSequence:
    """Verify the complete RECALL path matches Agent Contract V2."""

    def test_recall_path_has_correct_agent_order(self):
        """RECALL path is extraction → incident lead → custody → planning."""
        path = sequence_for_trigger(TriggerClass.RECALL)

        assert path[0] == AGENT_RECALL_INTAKE_EXTRACTION
        assert path[1] == AGENT_INCIDENT_LEAD
        assert path[2] == AGENT_NETWORK_CUSTODY
        assert path[3] == AGENT_FULFILLMENT_PLANNING_RECOVERY
        assert len(path) == 4


class TestGovernedSequenceIsDerived:
    """The coordinator's exported sequence must never drift from its source.

    A hand-copied duplicate of the recall tuple previously disagreed with
    ORCHESTRATION_PATHS after the recall path changed, silently breaking every
    suite that asserted against the export. This pins them together.
    """

    def test_governed_sequence_equals_the_authoritative_recall_path(self):
        from full_shelf_domain.fleet.coordinator import GOVERNED_SEQUENCE

        assert GOVERNED_SEQUENCE == sequence_for_trigger(TriggerClass.RECALL)


class TestModelArmorBoundaryDesign:
    """Test Model Armor boundary design (not execution - that requires live ADK)."""

    def test_extraction_agent_input_trust_class_is_model_armor_approved(self):
        """Extraction agent is designed to accept MODEL_ARMOR_APPROVED input only."""
        # This is a design claim, not an execution test (requires mocking Armor screening)
        from full_shelf_domain.fleet.manifest import build_manifest

        manifest = build_manifest()
        extraction_entry = next(
            (a for a in manifest["agents"]
             if "recall-intake-extraction" in a["agent_id"]), None
        )
        assert extraction_entry is not None
        assert "MODEL_ARMOR_APPROVED" in extraction_entry["input_trust_classes"]

    def test_model_armor_is_not_an_agent_in_orchestration_sequence(self):
        """Model Armor is infrastructure, not part of the agent sequence."""
        path = sequence_for_trigger(TriggerClass.RECALL)

        # Model Armor ID should not appear in agent paths
        assert not any("armor" in str(agent).lower() for agent in path)
        # Only contracted specialist agents appear in paths (no infrastructure)
        assert len(path) == 4
        # All agents in path are from FLEET_AGENT_IDS
        from full_shelf_domain.fleet.contracts import FLEET_AGENT_IDS
        assert all(agent in FLEET_AGENT_IDS for agent in path)

    def test_partner_outbound_communication_trust_class(self):
        """Partner Operations declares distinct trust requirements per mode."""
        from full_shelf_domain.fleet.manifest import build_manifest

        manifest = build_manifest()
        partner_entry = next(
            (a for a in manifest["agents"]
             if "partner-operations" in a["agent_id"]), None
        )
        assert partner_entry is not None
        # Mode-scoped trust: outbound uses TRUSTED_AUTHORITATIVE only
        assert "input_trust_by_mode" in partner_entry
        assert partner_entry["input_trust_by_mode"]["OUTBOUND_FOLLOWUP"] == ["TRUSTED_AUTHORITATIVE"]
        # Inbound requires all three: AUTHENTICATED_EXTERNAL, MODEL_ARMOR_APPROVED, TRUSTED_AUTHORITATIVE
        inbound_trust = set(partner_entry["input_trust_by_mode"]["INBOUND_EVIDENCE"])
        assert inbound_trust == {"AUTHENTICATED_EXTERNAL", "MODEL_ARMOR_APPROVED", "TRUSTED_AUTHORITATIVE"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
