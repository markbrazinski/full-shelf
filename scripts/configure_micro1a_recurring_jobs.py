#!/usr/bin/env python3
"""Migrate ordinary daily jobs and create untouched Micro 1A audit reserves."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CONFIGURE = ROOT / "scripts" / "configure_operating_day_scheduler.py"

JOBS = (
    {
        "job": "full-shelf-daily-plan-job",
        "tenant": "east-bay-food-bank",
        "fixture": "canonical",
        "topic": "full-shelf-incidents",
        "role": "ORDINARY_PRODUCTION",
    },
    {
        "job": "full-shelf-delta-canonical-daily",
        "tenant": "audit-canonical",
        "fixture": "canonical",
        "topic": "full-shelf-delta-audit",
        "role": "ORDINARY_AUDIT_EXISTING",
    },
    {
        "job": "full-shelf-delta-altered-daily",
        "tenant": "audit-altered",
        "fixture": "altered",
        "topic": "full-shelf-delta-audit",
        "role": "ORDINARY_AUDIT_EXISTING",
    },
    {
        "job": "full-shelf-micro1a-builder-daily",
        "tenant": "audit-canonical-builder-m1a",
        "fixture": "canonical",
        "topic": "full-shelf-delta-audit",
        "role": "BUILDER_QUALIFICATION",
    },
    {
        "job": "full-shelf-micro1a-auditor-canonical-daily",
        "tenant": "audit-canonical-auditor-a",
        "fixture": "canonical",
        "topic": "full-shelf-delta-audit",
        "role": "AUDITOR_RESERVED_DO_NOT_TRIGGER",
    },
    {
        "job": "full-shelf-micro1a-auditor-altered-daily",
        "tenant": "audit-altered-auditor-b",
        "fixture": "altered",
        "topic": "full-shelf-delta-audit",
        "role": "AUDITOR_RESERVED_DO_NOT_TRIGGER",
    },
)


def main() -> int:
    configured = []
    for spec in JOBS:
        command = [
            sys.executable,
            str(CONFIGURE),
            f"--fixture={spec['fixture']}",
            f"--tenant-id={spec['tenant']}",
            f"--job-name={spec['job']}",
            f"--topic={spec['topic']}",
            f"--description=Full Shelf {spec['role']} date-free recurring daily job",
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        configured.append(spec)
    print(json.dumps({"configured": configured}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
