#!/usr/bin/env python3
"""Configure one enabled, date-free ordinary recurring daily job."""

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
    return subprocess.run(
        args, cwd=ROOT, env=env, check=check, text=True, capture_output=True
    )


def build_recurring_request(*, fixture: str, tenant_id: str) -> dict:
    fixture_name = (
        "audit_canonical_shaped.json" if fixture == "canonical"
        else "audit_altered.json"
    )
    fixture_data = json.loads((ROOT / "test-fixtures" / fixture_name).read_text())
    return {
        "event_type": "PLAN_DAY_REQUESTED",
        "tenant_id": tenant_id,
        "operating_plan": fixture_data["operating_plan"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=["canonical", "altered"], required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--topic", default=TOPIC)
    parser.add_argument(
        "--description",
        default="Full Shelf date-free ordinary recurring daily plan request",
    )
    args = parser.parse_args()

    body = build_recurring_request(fixture=args.fixture, tenant_id=args.tenant_id)
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
        json.dump(body, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        exists = run([
            "gcloud", "scheduler", "jobs", "describe", args.job_name,
            f"--location={LOCATION}", f"--project={PROJECT}", "--format=value(name)",
        ], check=False).returncode == 0
        verb = "update" if exists else "create"
        run([
            "gcloud", "scheduler", "jobs", verb, "pubsub", args.job_name,
            f"--location={LOCATION}", f"--project={PROJECT}", f"--topic={args.topic}",
            "--schedule=30 5 * * *", "--time-zone=America/Los_Angeles",
            f"--message-body-from-file={handle.name}",
            f"--description={args.description}",
            "--quiet",
        ])
    run([
        "gcloud", "scheduler", "jobs", "resume", args.job_name,
        f"--location={LOCATION}", f"--project={PROJECT}", "--quiet",
    ], check=False)
    print(json.dumps({
        "tenant_id": args.tenant_id,
        "operating_day_source": "verified_pubsub_publish_time",
        "operating_time_zone": "America/Los_Angeles",
        "job": args.job_name,
        "state": "ENABLED",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
