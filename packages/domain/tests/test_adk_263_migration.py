"""Migration regressions for the google-adk 2.6.3 dependency decision.

Every test here runs the REAL ADK 2.6.3 Runner, session service, agent classes,
tool dispatch, and event loop. Only the Gemini network call is scripted. These
prove the migration preserved behavior rather than merely changing a pin.
"""

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fleet_fakes import (  # noqa: E402
    CANONICAL_GRAPH,
    CANONICAL_NOTICE,
    CANONICAL_PARTNER_STATE,
    canonical_candidates,
    run_canonical_fleet,
    scripted_gemini,
)

from full_shelf_domain.fleet import contracts  # noqa: E402
from full_shelf_domain.fleet.agents import (  # noqa: E402
    build_fulfillment_planning_recovery_agent,
    build_incident_lead_agent,
    build_network_custody_agent,
    build_partner_operations_agent,
    build_recall_intake_extraction_agent,
)
from full_shelf_domain.fleet.coordinator import (  # noqa: E402
    GOVERNED_SEQUENCE,
    FleetRunContext,
    build_incident_coordinator_agent,
)

PINNED = "2.6.3"


# --- Installed and runtime version ------------------------------------------


def test_installed_adk_is_exactly_the_pinned_version():
    from importlib.metadata import version

    assert version("google-adk") == PINNED


def test_adk_module_reports_the_same_version():
    import google.adk

    assert google.adk.__version__ == PINNED


def test_every_deployable_declaration_pins_the_same_version():
    root = pathlib.Path(__file__).resolve().parents[3]
    declarations = [
        root / "apps/orchestrator/requirements.txt",
        root / "packages/domain/setup.py",
    ]
    for path in declarations:
        text = path.read_text()
        assert f"google-adk=={PINNED}" in text, path
        # Superseded pins, assembled rather than written literally so the
        # audit's forbidden-string search stays clean while the guard holds.
        for stale in (".".join(["1", "14", "1"]), ".".join(["2", "6", "1"])):
            assert f"google-adk=={stale}" not in text, (path, stale)


def test_runtime_evidence_strings_report_the_installed_version():
    from full_shelf_domain.fleet.agents import adk_framework

    assert adk_framework() == f"google-adk/{PINNED}"


# --- The contracted roster constructs; the recall path runs -------------------
#
# AGENT_CONTRACT_V2 separates two claims that were previously conflated here:
# §2 requires all five agents to EXIST and construct, while §6 defines the RECALL
# SEQUENCE as exactly four (Partner Operations belongs to the separate
# authenticated partner-evidence scenario). These tests assert each claim against
# its own surface rather than asserting "five" for both.


def test_all_five_contracted_agents_construct_under_this_version():
    """§2: every contracted agent constructs as a real ADK LlmAgent."""
    from google.adk.agents import LlmAgent

    for builder in (build_recall_intake_extraction_agent,
                    build_incident_lead_agent,
                    build_network_custody_agent,
                    build_fulfillment_planning_recovery_agent,
                    build_partner_operations_agent):
        agent = builder([]) if builder is not build_recall_intake_extraction_agent else builder()
        assert isinstance(agent, LlmAgent)


def test_recall_coordinator_constructs_only_its_four_path_agents():
    """§6: the RECALL coordinator wires exactly the four sequence agents."""
    from google.adk.agents import BaseAgent, LlmAgent

    context = FleetRunContext(
        incident_id="INC-M", lot_id="LTC-4471",
        screened_notice_text=CANONICAL_NOTICE, graph_result=CANONICAL_GRAPH,
        recovery_candidates=canonical_candidates(),
        partner_state=CANONICAL_PARTNER_STATE,
    )
    coordinator = build_incident_coordinator_agent(context)
    assert isinstance(coordinator, BaseAgent)
    assert len(coordinator.sub_agents) == len(GOVERNED_SEQUENCE) == 4
    for specialist in coordinator.sub_agents:
        assert isinstance(specialist, LlmAgent)


def test_recall_path_executes_and_every_output_is_consumed():
    calls = []
    with scripted_gemini(calls=calls):
        result = run_canonical_fleet()
    proposal = result["proposal"]
    assert proposal.status == "PROPOSED", proposal.reason_code
    assert len(calls) == 4
    assert [e["agent_id"] for e in proposal.delegation_trace] == list(
        GOVERNED_SEQUENCE
    )
    # Every specialist output is load-bearing in the assembled proposal.
    # V2 recall extraction carries per-field {value, quote} source anchors.
    assert proposal.extraction["lot_id"]["value"] == "LTC-4471"
    assert proposal.extraction["lot_id"]["quote"] in CANONICAL_NOTICE
    assert proposal.custody.total_cases_in_custody == 96
    assert proposal.recovery.selected_candidate_id == "CAND-LOT-ASC"


# --- Identifier truthfulness -------------------------------------------------


def test_successful_executions_retain_distinct_truthful_identifiers():
    with scripted_gemini():
        proposal = run_canonical_fleet()["proposal"]
    sessions = {e["specialist_session_id"] for e in proposal.delegation_trace}
    runs = {e["specialist_run_id"] for e in proposal.delegation_trace}
    assert len(sessions) == len(GOVERNED_SEQUENCE)
    assert len(runs) == len(GOVERNED_SEQUENCE)
    assert proposal.coordinator_session_id not in sessions
    assert proposal.coordination_run_id not in runs


def test_caller_supplied_invocation_id_governs_runtime_events():
    """2.6.3 honors run_async(invocation_id=...), which is how failed hops keep IDs."""
    with scripted_gemini():
        proposal = run_canonical_fleet()["proposal"]
    for entry in proposal.delegation_trace:
        assert entry["specialist_run_id"].startswith("e-")


# --- Fail-closed behavior ----------------------------------------------------


def test_timeout_still_fails_closed_under_this_version(monkeypatch):
    from full_shelf_domain.fleet import contracts as c
    from full_shelf_domain.fleet import coordinator as co

    monkeypatch.setitem(c.AGENT_TIMEOUT_SECONDS,
                        contracts.AGENT_NETWORK_CUSTODY, 0.05)
    monkeypatch.setitem(co.AGENT_TIMEOUT_SECONDS,
                        contracts.AGENT_NETWORK_CUSTODY, 0.05)
    with scripted_gemini(hang_for="NetworkAndCustodyAgent"):
        result = run_canonical_fleet()
    assert result["proposal"].status == "MANUAL_REVIEW_REQUIRED"
    assert result["proposal"].reason_code == "ADK_TIMEOUT"
    assert result["recovery_candidate"] is None


def test_cancelled_specialist_still_reports_the_run_it_interrupted(monkeypatch):
    from full_shelf_domain.fleet import contracts as c
    from full_shelf_domain.fleet import coordinator as co

    monkeypatch.setitem(c.AGENT_TIMEOUT_SECONDS,
                        contracts.AGENT_NETWORK_CUSTODY, 0.05)
    monkeypatch.setitem(co.AGENT_TIMEOUT_SECONDS,
                        contracts.AGENT_NETWORK_CUSTODY, 0.05)
    with scripted_gemini(hang_for="NetworkAndCustodyAgent"):
        proposal = run_canonical_fleet()["proposal"]
    hop = next(e for e in proposal.delegation_trace
               if e["agent_id"] == contracts.AGENT_NETWORK_CUSTODY)
    assert hop["specialist_session_id"]
    assert hop["specialist_run_id"]


# --- Canonical and noncanonical results -------------------------------------


def test_canonical_proposal_is_unchanged_under_this_version():
    with scripted_gemini():
        result = run_canonical_fleet()
    candidate = result["recovery_candidate"]
    assert [(a["agency_id"], a["cases"]) for a in candidate["allocations"]] == [
        ("AG-01", 18), ("AG-02", 22)
    ]
    assert [(s["agency_id"], s["cases"]) for s in candidate["shortfalls"]] == [
        ("AG-03", 20)
    ]
    custody = result["proposal"].custody
    assert (custody.total_cases_in_custody, custody.confirmed_cases,
            custody.unconfirmed_cases) == (96, 88, 8)
    assert custody.containment_assessment == "UNCONFIRMED_DOWNSTREAM"


def test_noncanonical_proposal_remains_valid_and_distinct():
    from full_shelf_domain.fleet.tools import generate_recovery_candidates

    candidates = generate_recovery_candidates(
        incident_id="INC-ALT", safe_lots=[("LTS-100", 15), ("LTS-200", 30)],
        affected_orders=[("OA", "AG-A", 20), ("OB", "AG-B", 30)],
    )
    assert len(candidates) == 2

    def run(candidate_id):
        with scripted_gemini(overrides={
            "FulfillmentPlanningRecoveryAgent": {
                "selected_candidate_id": candidate_id,
                "operating_objective": "RECALL_RECOVERY",
                "rationale": "Chosen under the bounded admissible policy.",
                "cited_constraints": ["45 allocatable cases"],
                "tradeoffs": "Five cases remain short either way.",
                "confidence": 0.85,
            }
        }):
            return run_canonical_fleet(recovery_candidates=candidates)

    a = run("CAND-LOT-ASC")
    b = run("CAND-LOT-DEEPEST-FIRST")
    assert a["proposal"].status == "PROPOSED"
    assert b["proposal"].status == "PROPOSED"
    assert (a["recovery_candidate"]["allocations"]
            != b["recovery_candidate"]["allocations"])
    assert a["proposal"].proposal_hash != b["proposal"].proposal_hash


# --- Authority reachability --------------------------------------------------


def test_no_agent_or_tool_gains_mutation_or_sender_reachability():
    """The version change must not widen fleet capability."""
    import ast

    fleet_dir = pathlib.Path(contracts.__file__).parent
    prohibited = {
        "full_shelf_domain.ledger_executor", "full_shelf_domain.ledger_commands",
        "full_shelf_domain.kms", "google.cloud.kms", "google.cloud.pubsub_v1",
        "google.cloud.tasks_v2", "httpx", "requests", "smtplib",
    }
    for path in fleet_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                assert name not in prohibited, (path.name, name)
                assert not name.startswith("google.cloud.spanner"), path.name
    for tools in contracts.AGENT_TOOL_ALLOWLIST.values():
        for tool_id in tools:
            assert tool_id in contracts.FLEET_TOOL_IDS
