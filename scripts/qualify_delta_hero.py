#!/usr/bin/env python3
"""Run one isolated hero loop only through deployed product entry points."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import logging_v2, secretmanager, spanner

from full_shelf_domain.recall import schedule_site01_deadline_task


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
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    fixture_name = (
        "audit_canonical_shaped.json"
        if args.fixture == "canonical"
        else "audit_altered.json"
    )
    fixture = json.loads((ROOT / "test-fixtures" / fixture_name).read_text())
    tenant_id = args.tenant_id
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

    hold_rows = _rows(
        database,
        "SELECT incident_id, details FROM Incidents WHERE tenant_id=@tenant "
        "AND incident_type='DEADLINE_HOLD'",
        tenant_id,
    )
    if len(hold_rows) != 1:
        raise SystemExit("exactly one committed acknowledgment hold required")
    hold_details = json.loads(hold_rows[0][1])
    event_key = hold_details["task_name"]
    duplicate_task_names = []
    task_prefix = hashlib.sha256(tenant_id.encode()).hexdigest()[:16]
    for suffix in ("a", "b"):
        task = schedule_site01_deadline_task(
            tenant_id=tenant_id,
            incident_id=recall["incident_id"],
            hold_incident_id=hold_rows[0][0],
            coordinator_id=coordinator["coordinator_id"],
            lot_id=recall["lot_id"],
            site_id=hold_details["site_id"],
            unconfirmed_cases=hold_details["unconfirmed_cases"],
            task_id=f"duplicate-{task_prefix}-{suffix}",
            event_idempotency_key=event_key,
            orchestrator_url=ORCHESTRATOR,
            oidc_audience=ORCHESTRATOR,
            delivery_service_account=(
                "full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com"
            ),
        )
        duplicate_task_names.append(task["task_name"])

    receipt_count_before_duplicates = len(receipts)
    logging_client = logging_v2.Client(project=PROJECT)
    duplicate_deadline = time.monotonic() + args.timeout
    while time.monotonic() < duplicate_deadline:
        after_duplicate_receipts = _rows(
            database,
            "SELECT receipt_id, action_type, status, mutations_applied, trace_id, "
            "idempotency_key, timestamp FROM Receipts WHERE tenant_id=@tenant "
            "ORDER BY timestamp, receipt_id",
            tenant_id,
        )
        entries = logging_client.list_entries(
            filter_=(
                'resource.type="cloud_run_revision" AND '
                'resource.labels.service_name="full-shelf-orchestrator" AND '
                f'textPayload:"duplicate-{task_prefix}-"'
            ),
            order_by=logging_v2.DESCENDING,
            max_results=50,
        )
        logs = "\n".join(
            entry.payload for entry in entries if isinstance(entry.payload, str)
        )
        if (
            len(after_duplicate_receipts) == receipt_count_before_duplicates
            and f"duplicate-{task_prefix}-a" in logs
            and f"duplicate-{task_prefix}-b" in logs
            and logs.count("idempotent_replay=True") >= 2
        ):
            break
        if len(after_duplicate_receipts) != receipt_count_before_duplicates:
            raise SystemExit("duplicate task delivery created an additional receipt")
        time.sleep(3)
    else:
        raise SystemExit("two managed duplicate task deliveries were not observed")

    credentials, _ = google.auth.default(scopes=[
        "https://www.googleapis.com/auth/cloud-platform"
    ])
    credentials.refresh(GoogleAuthRequest())
    scheduler_response = httpx.post(
        "https://cloudscheduler.googleapis.com/v1/"
        f"projects/{PROJECT}/locations/us-central1/jobs/"
        f"full-shelf-delta-{args.fixture}-next-day:run",
        headers={"Authorization": f"Bearer {credentials.token}"},
        json={},
        timeout=30,
    )
    scheduler_response.raise_for_status()
    next_day_deadline = time.monotonic() + args.timeout
    while time.monotonic() < next_day_deadline:
        next_day = _rows(
            database,
            "SELECT plan_id, revision, status FROM PlanRevisions "
            "WHERE tenant_id=@tenant AND revision='rev01'",
            tenant_id,
        )
        if len(next_day) == 1 and next_day[0][2] == "DRAFT_WITH_CONSTRAINTS":
            break
        time.sleep(3)
    else:
        raise SystemExit("managed next-day Scheduler delivery did not commit")

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
        "duplicate_task_names": duplicate_task_names,
        "duplicate_task_event_idempotency_key": event_key,
        "receipt_count_before_duplicate_tasks": receipt_count_before_duplicates,
        "receipt_count_after_duplicate_tasks": len(after_duplicate_receipts),
        "next_day_plan": next_day,
    }
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
