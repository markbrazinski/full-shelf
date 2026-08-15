"""Run WP2 mutations only against an explicitly isolated Spanner database."""

import json
import os
from datetime import datetime, timedelta, timezone

from google.cloud import spanner

from full_shelf_domain.identity import VerifiedGoogleIdentity
from full_shelf_domain.ledger_commands import LedgerCommand
from full_shelf_domain.ledger_executor import SpannerLedgerCommandExecutor
from full_shelf_domain.spanner import get_spanner_database


AUDIT_TENANT = "wp2-audit-tenant-20260813-v3"


def require_isolated_database() -> str:
    database_id = os.getenv("SPANNER_DATABASE_ID", "")
    if not database_id or database_id == "full-shelf-main" or "audit" not in database_id:
        raise RuntimeError("Refusing WP2 verification outside an explicitly named audit database")
    return database_id


def seed_audit_authority(database) -> None:
    def seed(transaction):
        rows = transaction.execute_sql(
            "SELECT tenant_id FROM Tenants WHERE tenant_id = @tenant_id",
            params={"tenant_id": AUDIT_TENANT},
            param_types={"tenant_id": spanner.param_types.STRING},
        )
        if next(iter(rows), None):
            return
        transaction.insert(
            table="Tenants",
            columns=["tenant_id", "name", "created_at"],
            values=[[AUDIT_TENANT, "WP2 isolated audit tenant", spanner.COMMIT_TIMESTAMP]],
        )
        transaction.insert(
            table="Lots",
            columns=[
                "tenant_id",
                "lot_id",
                "code",
                "produce_type",
                "hazard_status",
                "total_cases",
                "created_at",
            ],
            values=[
                [
                    AUDIT_TENANT,
                    "LOT-ALT-908",
                    "ALT-908",
                    "Altered Test Produce",
                    "SAFE",
                    13,
                    spanner.COMMIT_TIMESTAMP,
                ],
                [
                    AUDIT_TENANT,
                    "LOT-ALT-SAFE-909",
                    "ALT-SAFE-909",
                    "Altered Safe Replacement",
                    "SAFE",
                    9,
                    spanner.COMMIT_TIMESTAMP,
                ],
            ],
        )
        transaction.insert(
            table="PlanRevisions",
            columns=["tenant_id", "plan_id", "revision", "status", "created_at"],
            values=[[
                AUDIT_TENANT,
                "PLAN-ALT-2026-08-14",
                "rev42",
                "ACTIVE",
                spanner.COMMIT_TIMESTAMP,
            ]],
        )

    database.run_in_transaction(seed)


def command(command_id, idempotency_key, command_type, payload, expected="rev42"):
    agent_role = (
        "FULFILLMENT_RECOVERY_PLANNER"
        if command_type in {"SAVE_PLAN_REVISION", "ALLOCATE_SAFE_STOCK"}
        else "INCIDENT_COORDINATOR"
    )
    return LedgerCommand.model_validate(
        {
            "command_id": command_id,
            "idempotency_key": idempotency_key,
            "tenant_id": AUDIT_TENANT,
            "incident_id": payload.get("incident_id", "INC-ALT-777"),
            "agent_role": agent_role,
            "command_type": command_type,
            "expected_plan_revision": expected,
            "trace_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "payload": payload,
        }
    )


def main() -> None:
    database_id = require_isolated_database()
    database = get_spanner_database()
    seed_audit_authority(database)
    executor = SpannerLedgerCommandExecutor(
        database,
        allowed_tenant_ids={AUDIT_TENANT},
    )
    identity = VerifiedGoogleIdentity(
        subject="105774551577568412756",
        email="full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com",
        audience="https://full-shelf-plan-ledger-620464070103.us-central1.run.app",
        issuer="https://accounts.google.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    coordinator = command(
        "CMD-WP2-AUDIT-COORD",
        "wp2:audit:coordinator",
        "PERSIST_COORDINATOR",
        {
            "coordinator_id": "COORD-ALT-777",
            "state": "WAITING_FOR_EVENTS",
            "checkpoint": "CHK-ALT-777",
            "active_plan_revision": "rev42",
            "child_incident_ids": [],
        },
    )
    first = executor.execute(coordinator, identity)
    duplicate = executor.execute(coordinator.model_copy(update={"command_id": "CMD-WP2-AUDIT-REDRIVE"}), identity)
    stale = executor.execute(
        command(
            "CMD-WP2-AUDIT-STALE",
            "wp2:audit:stale",
            "PERSIST_COORDINATOR",
            coordinator.payload,
            expected="rev41",
        ),
        identity,
    )
    opened = executor.execute(
        command(
            "CMD-WP2-AUDIT-OPEN",
            "wp2:audit:open-recall",
            "OPEN_RECALL_INCIDENT",
            {
                "incident_id": "INC-ALT-777",
                "coordinator_id": "COORD-ALT-777",
                "lot_id": "LOT-ALT-908",
                "source_event_id": "wp2-isolated-recall",
                "source_publish_time": "2026-08-14T15:00:00Z",
                "model_armor_correlation_id": "0123456789abcdef0123456789abcdef",
                "details": {"hazard": "ALTERED_TEST_HAZARD", "cases": 13},
            },
        ),
        identity,
    )
    barrier = executor.execute(
        command(
            "CMD-WP2-AUDIT-BARRIER",
            "wp2:audit:barrier",
            "ACTIVATE_MOVEMENT_BARRIER",
            {
                "barrier_id": "BARRIER-ALT-908",
                "incident_id": "INC-ALT-777",
                "lot_id": "LOT-ALT-908",
                "reason": "ALTERED_TEST_RECALL",
                "work_item_id": "WORK-ALT-908-ROOT",
            },
        ),
        identity,
    )
    recovery = executor.execute(
        command(
            "CMD-WP2-AUDIT-RECOVERY",
            "wp2:audit:recovery",
            "ALLOCATE_SAFE_STOCK",
            {
                "incident_id": "INC-ALT-777",
                "allocations": [
                    {
                        "allocation_id": "ALLOC-ALT-AGENCY-X",
                        "agency_id": "AGENCY-X",
                        "lot_id": "LOT-ALT-SAFE-909",
                        "cases": 7,
                    }
                ],
                "shortfalls": [
                    {
                        "shortfall_id": "SHORT-ALT-AGENCY-Y",
                        "agency_id": "AGENCY-Y",
                        "cases": 3,
                    }
                ],
            },
        ),
        identity,
    )
    refusal = executor.execute(
        command(
            "CMD-WP2-AUDIT-REFUSAL",
            "wp2:audit:refusal",
            "RECORD_REFUSAL",
            {
                "incident_id": "INC-ALT-777",
                "subject_id": "SITE-ALT-Y",
                "reason": "ALTERED_ACKNOWLEDGMENT_UNCONFIRMED",
                "affected_cases": 3,
            },
        ),
        identity,
    )

    with database.snapshot(multi_use=True) as snapshot:
        receipt_count = next(
            iter(
                snapshot.execute_sql(
                    "SELECT COUNT(*) FROM Receipts WHERE tenant_id = @tenant_id",
                    params={"tenant_id": AUDIT_TENANT},
                    param_types={"tenant_id": spanner.param_types.STRING},
                )
            )
        )[0]
        barrier_count = next(
            iter(
                snapshot.execute_sql(
                    "SELECT COUNT(*) FROM MovementBarriers WHERE tenant_id = @tenant_id AND status = 'ACTIVE'",
                    params={"tenant_id": AUDIT_TENANT},
                    param_types={"tenant_id": spanner.param_types.STRING},
                )
            )
        )[0]
        work_item_count = next(
            iter(
                snapshot.execute_sql(
                    "SELECT COUNT(*) FROM WorkItems WHERE tenant_id = @tenant_id",
                    params={"tenant_id": AUDIT_TENANT},
                    param_types={"tenant_id": spanner.param_types.STRING},
                )
            )
        )[0]
        allocation_count = next(
            iter(
                snapshot.execute_sql(
                    "SELECT COUNT(*) FROM RecoveryAllocations WHERE tenant_id = @tenant_id",
                    params={"tenant_id": AUDIT_TENANT},
                    param_types={"tenant_id": spanner.param_types.STRING},
                )
            )
        )[0]
        shortfall_count = next(
            iter(
                snapshot.execute_sql(
                    "SELECT COUNT(*) FROM RecoveryShortfalls WHERE tenant_id = @tenant_id",
                    params={"tenant_id": AUDIT_TENANT},
                    param_types={"tenant_id": spanner.param_types.STRING},
                )
            )
        )[0]

    assert first.receipt["receipt_id"] == duplicate.receipt["receipt_id"]
    assert duplicate.idempotent_replay is True and duplicate.additional_mutations == 0
    assert stale.receipt["status"] == "DENIED" and stale.additional_mutations == 0
    assert opened.receipt["mutations_applied"] == 2
    assert opened.additional_mutations in {0, 2}
    assert barrier.receipt["mutations_applied"] == 3
    assert barrier.additional_mutations in {0, 3}
    assert recovery.receipt["mutations_applied"] == 2
    assert recovery.additional_mutations in {0, 2}
    assert refusal.receipt["status"] == "DENIED"
    assert refusal.additional_mutations == 0
    assert receipt_count == 6
    assert barrier_count == 1
    assert work_item_count == 1
    assert allocation_count == 1
    assert shortfall_count == 1

    print(
        json.dumps(
            {
                "database": database_id,
                "tenant": AUDIT_TENANT,
                "first_receipt": first.receipt["receipt_id"],
                "duplicate_receipt": duplicate.receipt["receipt_id"],
                "duplicate_additional_mutations": duplicate.additional_mutations,
                "replay_after_prior_commit": first.idempotent_replay,
                "stale_status": stale.receipt["status"],
                "stale_plan_mutations": stale.additional_mutations,
                "receipt_count": receipt_count,
                "active_barrier_count": barrier_count,
                "work_item_count": work_item_count,
                "recovery_allocation_count": allocation_count,
                "recovery_shortfall_count": shortfall_count,
                "refusal_status": refusal.receipt["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
