#!/usr/bin/env python3
"""Read both isolated custody graphs through the deployed orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from workload_identity import mint_orchestrator_workload_token


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = "https://full-shelf-orchestrator-620464070103.us-central1.run.app"


def main() -> int:
    workload_token = mint_orchestrator_workload_token(ORCHESTRATOR)
    evidence = {}
    with httpx.Client(
        base_url=ORCHESTRATOR,
        headers={"Authorization": f"Bearer {workload_token}"},
        timeout=60,
    ) as client:
        for fixture_name in ("audit_canonical_shaped.json", "audit_altered.json"):
            fixture = json.loads((ROOT / "test-fixtures" / fixture_name).read_text())
            tenant = fixture["tenant_id"]
            lot_id = fixture["recall"]["lot_id"]
            response = client.get(
                "/api/v1/orchestrator/custody/graph",
                params={"tenant_id": tenant, "lot_id": lot_id},
            )
            response.raise_for_status()
            result = response.json()
            evidence[tenant] = {
                "lot_id": lot_id,
                "unique_current_cases": result["unique_current_cases"],
                "confirmed_cases": result["confirmed_cases"],
                "unconfirmed_cases": result["unconfirmed_cases"],
                "maximum_custody_depth": result["max_path_depth"],
                "node_count": result["node_count"],
                "query_engine": result["query_engine"],
                "database_id": result["database_id"],
            }
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
