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
