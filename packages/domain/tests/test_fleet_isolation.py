"""Structural proof that no fleet module can reach mutation authority.

These tests read the fleet source itself rather than exercising behavior, so a
future edit that merely *imports* a ledger client, Spanner writer, KMS signer,
publisher, or outbound HTTP client fails here before any agent can run.
"""

import ast
import pathlib

import pytest

from full_shelf_domain.fleet import contracts


FLEET_DIR = pathlib.Path(contracts.__file__).parent
FLEET_MODULES = sorted(FLEET_DIR.glob("*.py"))

# Modules and attributes that carry, or can carry, authoritative write authority.
PROHIBITED_IMPORTS = {
    "full_shelf_domain.ledger_executor",
    "full_shelf_domain.ledger_commands",
    "full_shelf_domain.kms",
    "google.cloud.kms",
    "google.cloud.pubsub_v1",
    "google.cloud.tasks_v2",
    "httpx",
    "requests",
    "urllib.request",
    "smtplib",
}

# Spanner is readable by the orchestrator, but the fleet never touches the
# client directly: it receives already-read, normalized data from the caller.
PROHIBITED_IMPORTS_PREFIXES = ("google.cloud.spanner", "full_shelf_domain.ledger")

PROHIBITED_SYMBOLS = {
    "batch",
    "run_in_transaction",
    "insert_or_update",
    "commit",
    "execute_partitioned_dml",
    "asymmetric_sign",
    "publish",
    "create_task",
}


def _imported_names(path: pathlib.Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


@pytest.mark.parametrize("path", FLEET_MODULES, ids=lambda p: p.name)
def test_fleet_module_imports_no_mutation_authority(path):
    for name in _imported_names(path):
        assert name not in PROHIBITED_IMPORTS, f"{path.name} imports {name}"
        assert not name.startswith(PROHIBITED_IMPORTS_PREFIXES), (
            f"{path.name} imports {name}"
        )


@pytest.mark.parametrize("path", FLEET_MODULES, ids=lambda p: p.name)
def test_fleet_module_calls_no_mutation_methods(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in PROHIBITED_SYMBOLS, (
                f"{path.name} calls .{node.func.attr}()"
            )


def test_fleet_package_actually_contains_modules():
    # Guards against the parametrized tests silently passing on an empty glob.
    assert len(FLEET_MODULES) >= 2


def test_every_agent_has_an_explicit_tool_allowlist():
    assert set(contracts.AGENT_TOOL_ALLOWLIST) == set(contracts.FLEET_AGENT_IDS)
    for agent_id, tools in contracts.AGENT_TOOL_ALLOWLIST.items():
        assert isinstance(tools, tuple), agent_id
        for tool_id in tools:
            assert tool_id in contracts.FLEET_TOOL_IDS, (agent_id, tool_id)


def test_every_agent_has_a_bounded_timeout():
    assert set(contracts.AGENT_TIMEOUT_SECONDS) == set(contracts.FLEET_AGENT_IDS)
    assert all(0 < s <= 120 for s in contracts.AGENT_TIMEOUT_SECONDS.values())


def test_agent_output_schemas_forbid_extra_fields():
    for model in (
        contracts.NetworkCustodyAssessment,
        contracts.RecoverySelection,
        contracts.PartnerCommunication,
        contracts.FleetProposal,
    ):
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_recovery_selection_cannot_carry_quantities_or_destinations():
    # The planner may name a candidate; it may never restate a bound value.
    forbidden = {"cases", "quantity", "vehicle_id", "destination", "lot_id",
                 "revision", "deadline", "capacity"}
    assert not (set(contracts.RecoverySelection.model_fields) & forbidden)
