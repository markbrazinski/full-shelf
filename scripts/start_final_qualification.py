#!/usr/bin/env python3
"""Run one enabled daily Scheduler job and report its fresh authority scope."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone

from google.cloud import spanner


PROJECT = "preflight-hackathon"
INSTANCE = "fef-smoke-spanner"
DATABASE = "full-shelf-audit-wp6-20260813"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=["canonical", "altered"], required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    env = os.environ.copy()
    env.setdefault("CLOUDSDK_PYTHON", "/opt/homebrew/bin/python3.12")
    subprocess.run([
        "gcloud", "scheduler", "jobs", "run",
        f"full-shelf-delta-{args.fixture}-daily",
        "--location=us-central1", f"--project={PROJECT}", "--quiet",
    ], check=True, env=env)
    database = spanner.Client(project=PROJECT).instance(INSTANCE).database(DATABASE)
    prefix = f"audit-{args.fixture}-"
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        with database.snapshot() as snapshot:
            rows = list(snapshot.execute_sql(
                "SELECT tenant_id, created_at FROM Tenants "
                "WHERE STARTS_WITH(tenant_id, @prefix) AND created_at >= @started "
                "ORDER BY created_at DESC LIMIT 1",
                params={"prefix": prefix, "started": started},
                param_types={
                    "prefix": spanner.param_types.STRING,
                    "started": spanner.param_types.TIMESTAMP,
                },
            ))
        if rows:
            tenant_id, created_at = rows[0]
            date_token = tenant_id[len(prefix):len(prefix) + 8]
            operating_day = datetime.strptime(date_token, "%Y%m%d").date().isoformat()
            print(json.dumps({
                "fixture": args.fixture,
                "tenant_id": tenant_id,
                "operating_day": operating_day,
                "created_at": created_at.isoformat(),
                "scheduler_job": f"full-shelf-delta-{args.fixture}-daily",
            }, sort_keys=True))
            return 0
        time.sleep(3)
    raise SystemExit("fresh managed daily authority scope was not observed")


if __name__ == "__main__":
    raise SystemExit(main())
