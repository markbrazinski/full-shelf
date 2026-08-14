#!/usr/bin/env python3
"""Run one isolated hero loop only through deployed product entry points."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from google.cloud import secretmanager, spanner


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "preflight-hackathon"
INSTANCE = "fef-smoke-spanner"
DATABASE = "full-shelf-audit-wp6-20260813"
ORCHESTRATOR = (
    "https://full-shelf-orchestrator-620464070103.us-central1.run.app"
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _rows(database, sql: str, tenant_id: str) -> list[list[Any]]:
    with database.snapshot() as snapshot:
        result = snapshot.execute_sql(
            sql,
            params={"tenant": tenant_id},
            param_types={"tenant": spanner.param_types.STRING},
        )
        return [[_json_value(value) for value in row] for row in result]


def _post(client: httpx.Client, path: str, *, tenant_id: str, body: dict) -> dict:
    response = client.post(path, params={"tenant_id": tenant_id}, json=body)
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=["canonical", "altered"], required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    fixture_name = (
        "audit_canonical_shaped.json"
        if args.fixture == "canonical"
        else "audit_altered.json"
    )
    fixture = json.loads((ROOT / "test-fixtures" / fixture_name).read_text())
    tenant_id = fixture["tenant_id"]
    if not tenant_id.startswith("audit-") or "audit" not in DATABASE:
        raise SystemExit("isolated audit scope required")

    api_key = secretmanager.SecretManagerServiceClient().access_secret_version(
        request={
            "name": (
                f"projects/{PROJECT}/secrets/full-shelf-judge-api-key/"
                "versions/latest"
            )
        }
    ).payload.data.decode().strip()
    database = spanner.Client(project=PROJECT).instance(INSTANCE).database(DATABASE)

    approvals = _rows(
        database,
        "SELECT approval_id, source_revision, proposed_revision, plan_diff_hash, "
        "kms_key_version, trace_id FROM Approvals WHERE tenant_id=@tenant",
        tenant_id,
    )
    revisions = _rows(
        database,
        "SELECT plan_id, revision, status FROM PlanRevisions "
        "WHERE tenant_id=@tenant ORDER BY plan_id, revision",
        tenant_id,
    )
    if len(approvals) != 1 or not any(
        row[1:] == ["rev08", "ACTIVE"] for row in revisions
    ):
        raise SystemExit("one persisted approval and active rev08 required")

    coordinator = fixture["coordinator"]
    waiting_body = {
        **coordinator,
        "active_plan_revision": "rev08",
        "child_incident_ids": [coordinator["incident_id"]],
    }
    recall = fixture["recall"]
    headers = {"X-Full-Shelf-API-Key": api_key}
    with httpx.Client(base_url=ORCHESTRATOR, headers=headers, timeout=90) as client:
        waiting = _post(
            client,
            "/api/v1/orchestrator/coordinator/persist-waiting",
            tenant_id=tenant_id,
            body=waiting_body,
        )
        trigger = _post(
            client,
            "/api/v1/orchestrator/recall/trigger",
            tenant_id=tenant_id,
            body={"coordinator_id": coordinator["coordinator_id"], **recall},
        )

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        incidents = _rows(
            database,
            "SELECT incident_id, incident_type, status, terminal_state, "
            "affected_lot_id, details FROM Incidents WHERE tenant_id=@tenant "
            "ORDER BY incident_id",
            tenant_id,
        )
        receipts = _rows(
            database,
            "SELECT receipt_id, action_type, status, mutations_applied, trace_id, "
            "idempotency_key, timestamp FROM Receipts WHERE tenant_id=@tenant "
            "ORDER BY timestamp, receipt_id",
            tenant_id,
        )
        recall_complete = any(
            row[0] == recall["incident_id"] and row[2] == "PARTIALLY_CONTAINED"
            for row in incidents
        )
        task_complete = any(row[1] == "RECORD_ACKNOWLEDGMENT_HOLD" for row in receipts)
        if recall_complete and task_complete:
            break
        time.sleep(3)
    else:
        raise SystemExit("managed recall or Cloud Tasks callback did not complete")

    evidence = {
        "fixture": args.fixture,
        "tenant_id": tenant_id,
        "waiting_response": waiting,
        "recall_publish_response": trigger,
        "approvals": approvals,
        "plan_revisions": _rows(
            database,
            "SELECT plan_id, revision, status FROM PlanRevisions "
            "WHERE tenant_id=@tenant ORDER BY plan_id, revision",
            tenant_id,
        ),
        "coordinators": _rows(
            database,
            "SELECT coordinator_id, state, checkpoint, active_plan_revision, "
            "child_incidents FROM Coordinators WHERE tenant_id=@tenant "
            "ORDER BY coordinator_id",
            tenant_id,
        ),
        "incidents": incidents,
        "movement_barriers": _rows(
            database,
            "SELECT barrier_id, incident_id, lot_id, status FROM MovementBarriers "
            "WHERE tenant_id=@tenant ORDER BY barrier_id",
            tenant_id,
        ),
        "allocations": _rows(
            database,
            "SELECT allocation_id, incident_id, agency_id, lot_id, cases, status "
            "FROM RecoveryAllocations WHERE tenant_id=@tenant ORDER BY allocation_id",
            tenant_id,
        ),
        "shortfalls": _rows(
            database,
            "SELECT shortfall_id, incident_id, agency_id, cases, status "
            "FROM RecoveryShortfalls WHERE tenant_id=@tenant ORDER BY shortfall_id",
            tenant_id,
        ),
        "receipts": receipts,
    }
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
