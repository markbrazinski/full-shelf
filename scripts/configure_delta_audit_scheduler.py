#!/usr/bin/env python3
"""Create enabled, independently runnable Scheduler qualification jobs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "preflight-hackathon"
LOCATION = "us-central1"
TOPIC = "full-shelf-delta-audit"


def run(args, *, check=True):
    env = os.environ.copy()
    env.setdefault("CLOUDSDK_PYTHON", "/opt/homebrew/bin/python3.12")
    return subprocess.run(args, cwd=ROOT, env=env, check=check, text=True,
                          capture_output=True)


def upsert_job(name: str, body: dict):
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
        json.dump(body, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        exists = run([
            "gcloud", "scheduler", "jobs", "describe", name,
            f"--location={LOCATION}", f"--project={PROJECT}", "--format=value(name)",
        ], check=False).returncode == 0
        verb = "update" if exists else "create"
        run([
            "gcloud", "scheduler", "jobs", verb, "pubsub", name,
            f"--location={LOCATION}", f"--project={PROJECT}", f"--topic={TOPIC}",
            "--schedule=0 0 1 1 *", "--time-zone=Etc/UTC",
            f"--message-body-from-file={handle.name}",
            "--description=Enabled isolated Full Shelf fresh-scope qualification job",
            "--quiet",
        ])
    run(["gcloud", "scheduler", "jobs", "resume", name,
         f"--location={LOCATION}", f"--project={PROJECT}", "--quiet"], check=False)
    return name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=["canonical", "altered"], required=True)
    args = parser.parse_args()
    fixture_name = "audit_canonical_shaped.json" if args.fixture == "canonical" else "audit_altered.json"
    fixture = json.loads((ROOT / "test-fixtures" / fixture_name).read_text())
    suffix = args.fixture
    daily_name = f"full-shelf-delta-{suffix}-daily"
    next_name = f"full-shelf-delta-{suffix}-next-day"
    upsert_job(daily_name, {
        "event_type": "PLAN_DAY_REQUESTED",
        "qualification_profile": args.fixture,
        "operating_plan": fixture["operating_plan"],
    })
    upsert_job(next_name, {
        "event_type": "PLAN_NEXT_DAY_REQUESTED",
        "qualification_profile": args.fixture,
    })
    print(json.dumps({
        "tenant_prefix": f"audit-{args.fixture}-",
        "daily_job": daily_name,
        "next_day_job": next_name,
        "state": "ENABLED_MANUAL_QUALIFICATION",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
