"""Generate canonical v3.1 replay fixtures from the real production handler.

Fixtures are produced by driving the actual bounded-projection handler against
a faked Spanner snapshot, so they cannot drift into a shape the production code
would never emit. Nothing here calls Gemini, ADK, Model Armor, KMS, or any
cloud service, and every identifier is fixture-prefixed.

Run:  python tools/replay/generate_fixtures.py
"""

import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "orchestrator" / "tests"))
os.environ.setdefault("SPANNER_DATABASE_ID", "full-shelf-audit-wp6-20260813")
os.environ.setdefault("GRAPH_AUDIT_DATABASE_ID", "full-shelf-audit-wp6-20260813")

import test_bounded_projection as scenario  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

# Every v3.1 beat and the explicit as-of boundary that produces it.
BEATS = [
    ("healthy", scenario.T(8, 5), False),
    ("truckfail", scenario.T(8, 20), False),
    ("review", scenario.T(8, 21), False),
    ("geo", scenario.T(8, 22), False),
    ("rev08", scenario.T(8, 24), False),
    ("recall_received", scenario.T(9, 36), False),
    ("processing", scenario.T(10, 4), False),
    ("custody", scenario.T(10, 5), False),
    ("recovery", scenario.T(10, 10), False),
    ("refusal", scenario.T(10, 13), False),
    ("outcome", scenario.T(16, 30), False),
    ("tomorrow", scenario.T(17, 0), True),
]


def _reclassify(node):
    """Relabel every classification claim in a fixture as synthetic."""
    if isinstance(node, dict):
        return {
            key: "SYNTHETIC_TEST" if key == "classification" else _reclassify(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_reclassify(item) for item in node]
    return node


def main():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    index = []
    for name, as_of, include_next_day in BEATS:
        response = scenario.project(as_of, include_next_day=include_next_day)
        if response.status_code != 200:
            raise SystemExit(f"{name}: handler returned {response.status_code}")
        body = response.json()
        # Replay evidence is never presented as live or measured. Nested
        # evidence carries its own classification (the custody graph labels
        # itself OBSERVED_LIVE when read from Spanner), so reclassification
        # must reach every depth, not just the envelope.
        body = _reclassify(body)
        body["replay_notice"] = (
            "Fixture generated from the production handler against a faked "
            "snapshot. Not a real execution. No Gemini, ADK, Model Armor, KMS, "
            "or ledger evidence."
        )
        path = FIXTURES / f"{name}.json"
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        index.append({
            "beat": name,
            "as_of": as_of.isoformat(),
            "include_next_day_draft": include_next_day,
            "fixture": f"{name}.json",
        })
        print(f"  wrote {path.relative_to(REPO)}")
    (FIXTURES / "index.json").write_text(
        json.dumps({"operating_day": scenario.DAY,
                    "tenant_id": scenario.TENANT,
                    "classification": "SYNTHETIC_TEST",
                    "beats": index}, indent=2) + "\n")
    print(f"  wrote {(FIXTURES / 'index.json').relative_to(REPO)}")


if __name__ == "__main__":
    main()
