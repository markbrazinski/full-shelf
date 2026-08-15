#!/usr/bin/env python3
"""Reserve enabled, untriggered production-path jobs for the final auditor."""

from __future__ import annotations

import json
from pathlib import Path

from configure_delta_audit_scheduler import upsert_job


ROOT = Path(__file__).resolve().parents[1]
LOGICAL_TENANT = "audit-final-canonical"
OPERATING_DAY = "2026-08-14"
AUTHORITY_TENANT = "audit-final-canonical-20260814"
DAILY_JOB = "full-shelf-final-auditor-daily"
NEXT_DAY_JOB = "full-shelf-final-auditor-next-day"


def main() -> None:
    fixture = json.loads(
        (ROOT / "test-fixtures" / "audit_canonical_shaped.json").read_text()
    )
    upsert_job(DAILY_JOB, {
        "event_type": "PLAN_DAY_REQUESTED",
        "tenant_id": LOGICAL_TENANT,
        "operating_plan": fixture["operating_plan"],
    })
    upsert_job(NEXT_DAY_JOB, {
        "event_type": "PLAN_NEXT_DAY_REQUESTED",
        "tenant_id": AUTHORITY_TENANT,
    })
    print(json.dumps({
        "logical_tenant": LOGICAL_TENANT,
        "operating_day": OPERATING_DAY,
        "operating_day_derivation": (
            "verified Pub/Sub publishTime converted to America/Los_Angeles"
        ),
        "authority_tenant": AUTHORITY_TENANT,
        "daily_job": DAILY_JOB,
        "next_day_job": NEXT_DAY_JOB,
        "projection_authority": AUTHORITY_TENANT,
        "projection_operating_day": OPERATING_DAY,
        "sse_path": "/api/v1/projections/stream",
        "expected_plan_ids": {
            "day": "PLAN-AUDIT-CANONICAL/rev07 then rev08",
            "next_day": "PLAN-2026-08-15/rev01",
        },
        "state": "ENABLED_AUDITOR_RESERVED_DO_NOT_TRIGGER",
        "schedule": "0 0 1 1 *",
        "time_zone": "Etc/UTC",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
