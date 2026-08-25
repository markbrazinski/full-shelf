"""Generate canonical v3.1 replay fixtures from the real production handler.

Fixtures are produced by driving the actual bounded-projection handler against
a faked Spanner snapshot, so they cannot drift into a shape the production code
would never emit. Nothing here calls Gemini, ADK, Model Armor, KMS, or any
cloud service, and every identifier is fixture-prefixed.

Run:  python tools/replay/generate_fixtures.py
"""

import json
import copy
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

PROOFS = [
    ("partner_vague", scenario.T(10, 16), scenario.VAGUE_EVIDENCE_ROW,
     "fixture-partner-vague", "DENIED", 0, False),
    ("partner_complete", scenario.T(10, 19), scenario.COMPLETE_EVIDENCE_ROW,
     "fixture-partner-complete", "SUCCESS", 2, True),
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
    proof_index = []
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
    for name, as_of, evidence_row, source_event_id, status, mutations, complete in PROOFS:
        receipts = list(scenario.ALL_RECEIPTS) + [
            scenario.partner_receipt(source_event_id, evidence_row[27], status, mutations)
        ]
        work_rows = [(
            "WORK-PCF-FIXTURE", scenario.RECALL_INC,
            "COMPLETED" if complete else "OPEN", scenario.T(10, 5),
            scenario.T(10, 18) if complete else None,
        )]
        graph = copy.deepcopy(scenario.CUSTODY_GRAPH)
        if complete:
            for node in graph["current_positions"]:
                if node["node_id"] == "N-ST01":
                    node["acknowledgment_status"] = "CONFIRMED"
            graph["unconfirmed_positions"] = []
            graph["confirmed_cases"] = graph["unique_current_cases"]
            graph["unconfirmed_cases"] = 0
        db = scenario._database(
            receipts=receipts,
            work_rows=work_rows,
            partner_evidence_rows=[evidence_row],
        )
        response = scenario.project(as_of, db=db, custody_graph=graph)
        if response.status_code != 200:
            raise SystemExit(f"{name}: handler returned {response.status_code}")
        body = _reclassify(response.json())
        body["replay_notice"] = (
            "Isolated selected proof generated from the production projection "
            "handler against a synthetic authority. It does not rewrite the "
            "canonical filmed 88/96 timeline."
        )
        path = FIXTURES / f"{name}.json"
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        proof_index.append({
            "beat": name,
            "as_of": as_of.isoformat(),
            "include_next_day_draft": False,
            "fixture": f"{name}.json",
            "authority": "ISOLATED_SELECTED_PROOF",
        })
        print(f"  wrote {path.relative_to(REPO)}")
    index.sort(key=lambda entry: entry["as_of"])
    proof_index.sort(key=lambda entry: entry["as_of"])
    (FIXTURES / "index.json").write_text(
        json.dumps({"operating_day": scenario.DAY,
                    "tenant_id": scenario.TENANT,
                    "classification": "SYNTHETIC_TEST",
                    "beats": index,
                    "proofs": proof_index}, indent=2) + "\n")
    print(f"  wrote {(FIXTURES / 'index.json').relative_to(REPO)}")


if __name__ == "__main__":
    main()
