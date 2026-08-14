#!/usr/bin/env python3
"""Create enabled, untriggered Micro 2 next-day auditor reservations."""

from __future__ import annotations

import json

from configure_delta_audit_scheduler import upsert_job


JOBS = (
    {
        "name": "full-shelf-micro2-auditor-canonical-next-day",
        "tenant_id": "audit-canonical-20260814-bdc5262a76",
    },
    {
        "name": "full-shelf-micro2-auditor-altered-next-day",
        "tenant_id": "audit-altered-20260814-3505081ced",
    },
)


def main() -> None:
    configured = []
    for job in JOBS:
        upsert_job(job["name"], {
            "event_type": "PLAN_NEXT_DAY_REQUESTED",
            "tenant_id": job["tenant_id"],
        })
        configured.append({
            **job,
            "state": "ENABLED_AUDITOR_RESERVED_DO_NOT_TRIGGER",
            "schedule": "0 0 1 1 *",
            "time_zone": "Etc/UTC",
        })
    print(json.dumps(configured, sort_keys=True))


if __name__ == "__main__":
    main()
