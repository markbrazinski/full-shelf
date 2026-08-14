#!/usr/bin/env python3
"""Configure one enabled daily job with an ordinary OperatingDayRequest."""

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=["canonical", "altered"], required=True)
    parser.add_argument("--operating-day", required=True)
    parser.add_argument("--job-name")
    args = parser.parse_args()

    fixture_name = (
        "audit_canonical_shaped.json"
        if args.fixture == "canonical"
        else "audit_altered.json"
    )
    fixture = json.loads((ROOT / "test-fixtures" / fixture_name).read_text())
    tenant_id = f"audit-{args.fixture}"
    job_name = args.job_name or f"full-shelf-delta-{args.fixture}-daily"
    body = {
        "event_type": "PLAN_DAY_REQUESTED",
        "tenant_id": tenant_id,
        "operating_day": args.operating_day,
        "operating_plan": fixture["operating_plan"],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
        json.dump(body, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        exists = run([
            "gcloud", "scheduler", "jobs", "describe", job_name,
            f"--location={LOCATION}", f"--project={PROJECT}", "--format=value(name)",
        ], check=False).returncode == 0
        verb = "update" if exists else "create"
        run([
            "gcloud", "scheduler", "jobs", verb, "pubsub", job_name,
            f"--location={LOCATION}", f"--project={PROJECT}", f"--topic={TOPIC}",
            "--schedule=30 5 * * *", "--time-zone=America/Los_Angeles",
            f"--message-body-from-file={handle.name}",
            "--description=Full Shelf ordinary operating-day plan request",
            "--quiet",
        ])
    run([
        "gcloud", "scheduler", "jobs", "resume", job_name,
        f"--location={LOCATION}", f"--project={PROJECT}", "--quiet",
    ], check=False)
    print(json.dumps({
        "authority_scope": f"{tenant_id}@{args.operating_day}",
        "authority_tenant_id": f"{tenant_id}-{args.operating_day.replace('-', '')}",
        "job": job_name,
        "state": "ENABLED",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
