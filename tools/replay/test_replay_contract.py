"""Contract-parity and determinism tests for the deterministic replay harness.

These fail whenever the production projection contract and the replay fixtures
diverge, which is the whole point: replay is only useful if it cannot quietly
drift away from the real response shape.
"""

import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "orchestrator" / "tests"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
os.environ.setdefault("SPANNER_DATABASE_ID", "full-shelf-audit-wp6-20260813")

import test_bounded_projection as scenario  # noqa: E402
import server as replay  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
INDEX = json.loads((FIXTURES / "index.json").read_text())


def shape(value, path=""):
    """Structural signature: keys and types, ignoring values."""
    if isinstance(value, dict):
        out = {}
        for key in sorted(value):
            out[key] = shape(value[key], f"{path}.{key}")
        return out
    if isinstance(value, list):
        return [shape(value[0], path + "[]")] if value else []
    return type(value).__name__


@pytest.mark.parametrize("beat", [b["beat"] for b in INDEX["beats"]])
def test_fixture_matches_production_contract_shape(beat):
    """Every fixture must have the shape the production handler emits."""
    entry = next(b for b in INDEX["beats"] if b["beat"] == beat)
    as_of = scenario.datetime.fromisoformat(entry["as_of"])
    live = scenario.project(
        as_of, include_next_day=entry["include_next_day_draft"]).json()
    fixture = json.loads((FIXTURES / entry["fixture"]).read_text())
    fixture.pop("replay_notice", None)
    live.pop("replay_notice", None)
    # classification is deliberately re-labelled SYNTHETIC_TEST in replay.
    live["classification"] = "SYNTHETIC_TEST"
    assert shape(fixture) == shape(live), f"contract drift in beat {beat}"


def test_every_v31_beat_has_a_fixture():
    expected = {"healthy", "truckfail", "review", "geo", "rev08",
                "recall_received", "processing", "custody", "recovery",
                "refusal", "outcome", "tomorrow"}
    assert {b["beat"] for b in INDEX["beats"]} == expected


def test_replay_evidence_is_never_labelled_live_or_measured():
    for entry in INDEX["beats"]:
        body = json.loads((FIXTURES / entry["fixture"]).read_text())
        assert body["classification"] == "SYNTHETIC_TEST"
        blob = json.dumps(body)
        assert '"OBSERVED_LIVE"' not in blob
        assert '"MEASURED"' not in blob
        assert '"RECORDED_LIVE"' not in blob


def test_replay_is_deterministic_across_repeated_selection():
    a = replay._select("2026-08-14T10:13:00+00:00", False)
    b = replay._select("2026-08-14T10:13:00+00:00", False)
    assert a == b


def test_replay_beat_ordering_is_monotonic():
    stamps = [scenario.datetime.fromisoformat(b["as_of"]) for b in INDEX["beats"]]
    assert stamps == sorted(stamps)


def test_replay_excludes_future_state_at_early_boundary():
    healthy = replay._select("2026-08-14T08:05:00+00:00", False)
    blob = json.dumps(healthy)
    assert "rev08" not in blob
    assert scenario.RECALL_INC not in blob
    assert "next_day_draft" not in healthy


def test_replay_tomorrow_is_gated_behind_explicit_request():
    without = replay._select("2026-08-14T17:00:00+00:00", False)
    assert "next_day_draft" not in without
    with_draft = replay._select("2026-08-14T17:00:00+00:00", True)
    assert with_draft["next_day_draft"]["revision"] == "rev01"


def test_replay_server_binds_loopback_only():
    assert replay.LOOPBACK == "127.0.0.1"
    source = (pathlib.Path(__file__).resolve().parent / "server.py").read_text()
    assert "0.0.0.0" not in source


def test_replay_calls_no_google_service():
    source = (pathlib.Path(__file__).resolve().parent / "server.py").read_text()
    for banned in ("google.cloud", "spanner", "aiplatform", "vertexai",
                   "model_armor", "kms", "run_fleet", "httpx", "requests"):
        assert banned not in source, f"replay must not reference {banned}"


def test_replay_is_absent_from_deployment_configuration():
    for config in ("cloudbuild.yaml", "cloudbuild-orchestrator.yaml",
                   "cloudbuild-ledger.yaml"):
        text = (REPO / config).read_text()
        assert "tools/replay" not in text
        assert "replay" not in text.lower()
    for dockerfile in REPO.glob("apps/*/Dockerfile"):
        assert "tools/replay" not in dockerfile.read_text()


def test_fixture_identifiers_are_not_presented_as_real_managed_evidence():
    body = json.loads((FIXTURES / "refusal.json").read_text())
    assert body["replay_notice"].startswith("Fixture generated")


# --- production parity for malformed input ----------------------------------


def test_replay_rejects_malformed_as_of_the_way_production_does():
    """Production returns a structured 400 INVALID_AS_OF; replay must too."""
    with pytest.raises(replay.InvalidAsOf):
        replay._select("not-a-timestamp", False)


@pytest.mark.parametrize("bad", [
    "not-a-timestamp", "2026-13-45T99:99:99Z", "", "   ", "2026-08-14T10:13:00+99:00",
])
def test_every_malformed_as_of_shape_is_structured_not_a_crash(bad):
    if not bad:
        # An empty value is falsy and behaves as "no explicit boundary".
        assert replay._select(bad, False)
        return
    with pytest.raises(replay.InvalidAsOf):
        replay._select(bad, False)


def test_replay_http_layer_returns_400_invalid_as_of():
    """The handler must translate the malformed boundary into a real 400."""
    source = (pathlib.Path(__file__).resolve().parent / "server.py").read_text()
    assert "except InvalidAsOf:" in source
    assert '"detail": "INVALID_AS_OF"' in source


def test_valid_as_of_still_selects_a_beat():
    assert replay._select("2026-08-14T10:13:00Z", False)
    assert replay._select("2026-08-14T10:13:00+00:00", False)


# --- synthetic execution/evidence identifiers are visibly fixture-prefixed ---


SYNTHETIC_ID_FIELDS = (
    "coordinator_session_id", "coordination_run_id",
    "specialist_session_id", "specialist_run_id", "receipt_id",
)

# Canonical business identity is real domain data and must NOT be prefixed.
CANONICAL_BUSINESS_PREFIXES = ("INC-", "PLAN-", "LTC-", "AG-", "O2", "BARRIER-",
                               "WORK-", "SF-", "ALLOC-", "APR-")


def _walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


@pytest.mark.parametrize("beat", [b["beat"] for b in INDEX["beats"]])
def test_every_synthetic_execution_identifier_is_fixture_prefixed(beat):
    entry = next(b for b in INDEX["beats"] if b["beat"] == beat)
    body = json.loads((FIXTURES / entry["fixture"]).read_text())
    seen = 0
    for key, value in _walk(body):
        if key in SYNTHETIC_ID_FIELDS and isinstance(value, str) and value:
            assert value.startswith("fixture-"), (beat, key, value)
            seen += 1
    if beat in {"refusal", "outcome", "tomorrow"}:
        assert seen, f"{beat} should carry synthetic execution evidence"


def test_no_unprefixed_receipt_or_run_identifier_survives_anywhere():
    """A bare RCT-/sess-/run- identifier would read as real execution evidence."""
    import re

    for entry in INDEX["beats"]:
        blob = (FIXTURES / entry["fixture"]).read_text()
        for match in re.findall(r'"((?:RCT|sess|run)-[^"]*)"', blob):
            assert match.startswith("fixture-"), (entry["beat"], match)


def test_canonical_business_identifiers_are_never_fixture_prefixed():
    """Prefixing real domain identity would itself be a falsehood."""
    body = json.loads((FIXTURES / "refusal.json").read_text())
    assert body["current_day"]["plan_id"] == "PLAN-2026-08-14"
    incident_ids = [i["incident_id"] for i in body["current_day"]["incidents"]]
    assert scenario.RECALL_INC in incident_ids
    for incident_id in incident_ids:
        assert not incident_id.startswith("fixture-")
    for key, value in _walk(body):
        if isinstance(value, str) and value.startswith(CANONICAL_BUSINESS_PREFIXES):
            assert not value.startswith("fixture-"), (key, value)


def test_no_live_evidence_classification_appears_in_any_fixture():
    for entry in INDEX["beats"]:
        body = json.loads((FIXTURES / entry["fixture"]).read_text())
        assert body["classification"] == "SYNTHETIC_TEST"
        blob = json.dumps(body)
        for banned in ("OBSERVED_LIVE", "RECORDED_LIVE", "MEASURED",
                       "STRUCTURALLY_VERIFIED"):
            assert banned not in blob, (entry["beat"], banned)
