#!/usr/bin/env python3
"""Managed WP3 verification against an isolated Spanner database only."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from google.cloud import spanner

from full_shelf_domain.identity import VerifiedGoogleIdentity
from full_shelf_domain.kms import create_signed_approval_envelope, verify_kms_approval_envelope
from full_shelf_domain.ledger_commands import LedgerCommand
from full_shelf_domain.ledger_executor import SpannerLedgerCommandExecutor


def scalar(database, sql, params=None, param_types=None):
    with database.snapshot() as snapshot:
        return next(iter(snapshot.execute_sql(sql, params=params, param_types=param_types)))[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="preflight-hackathon")
    parser.add_argument("--instance", default="fef-smoke-spanner")
    parser.add_argument("--database", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--operator-sub", required=True)
    args = parser.parse_args()
    if "audit" not in args.database.lower() or args.database == "full-shelf-main":
        raise SystemExit("refusing non-audit database")

    database = spanner.Client(project=args.project).instance(args.instance).database(args.database)
    now = datetime.now(timezone.utc)
    plan_id, source_revision, proposed_revision = "PLAN-ALTERED-WP3", "rev42", "rev43"
    incident_id = "INC-TRUCK-ALTERED-WP3"

    with database.batch() as batch:
        batch.insert("Tenants", ["tenant_id", "name", "created_at"],
                     [[args.tenant, "WP3 altered audit tenant", spanner.COMMIT_TIMESTAMP]])
        batch.insert("PlanRevisions", ["tenant_id", "plan_id", "revision", "status", "created_at"],
                     [[args.tenant, plan_id, source_revision, "ACTIVE", spanner.COMMIT_TIMESTAMP]])
        batch.insert("Orders", ["tenant_id", "plan_id", "revision", "order_id",
                     "destination_agency_id", "destination_agency_name", "cases", "lot_id",
                     "assigned_vehicle_id", "status"], [[
                         args.tenant, plan_id, source_revision, "O202", "AG-ALT-2", "Altered 2",
                         22, "LOT-ALTERED", "TRUCK-01", "PLANNED"], [
                         args.tenant, plan_id, source_revision, "O203", "AG-ALT-3", "Altered 3",
                         20, "LOT-ALTERED", "TRUCK-01", "PLANNED"]])

    expiry = (now + timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
    envelope = create_signed_approval_envelope(
        approval_id="APP-WP3-ALTERED", rev_id=proposed_revision,
        principal_id=args.operator_sub, incident_id=incident_id,
        plan_id=plan_id, source_revision=source_revision, proposed_revision=proposed_revision,
        reroute_order_id="O202", reroute_cases=22, reroute_target_vehicle="TRUCK-02",
        pickup_order_id="O203", pickup_cases=20, expires_at=expiry,
    )
    if not verify_kms_approval_envelope(envelope):
        raise AssertionError("live KMS signature did not verify")

    tampered = envelope.model_copy(deep=True)
    tampered.plan_diff.pickup_cases = 21
    if verify_kms_approval_envelope(tampered):
        raise AssertionError("tampered envelope verified")
    expired = envelope.model_copy(deep=True)
    expired.expires_at = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    if verify_kms_approval_envelope(expired):
        raise AssertionError("expired envelope verified")

    identity = VerifiedGoogleIdentity(
        subject="105774551577568412756",
        email="full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com",
        audience="https://ledger.example.run.app", issuer="https://accounts.google.com",
        expires_at=now + timedelta(minutes=30),
    )
    command_values = {
        "command_id": "CMD-WP3-ALTERED", "idempotency_key": "wp3:altered:approval",
        "tenant_id": args.tenant, "incident_id": incident_id,
        "agent_role": "FULFILLMENT_RECOVERY_PLANNER",
        "command_type": "APPROVE_REPAIR_PLAN", "expected_plan_revision": source_revision,
        "trace_id": "abcdef0123456789abcdef0123456789",
        "payload": {"plan_id": plan_id, "source_revision": source_revision,
                    "proposed_revision": proposed_revision, "approval_id": envelope.approval_id,
                    "approver_subject": envelope.principal_id,
                    "approver_email": "altered-operator@example.com",
                    "oauth_audience": "altered-client.apps.googleusercontent.com",
                    "plan_diff_hash": envelope.plan_diff.plan_diff_hash,
                    "kms_key_version": envelope.kms_key_version,
                    "kms_signature": envelope.kms_signature, "expires_at": envelope.expires_at},
    }
    executor = SpannerLedgerCommandExecutor(database, allowed_tenant_ids={args.tenant})
    first = executor.execute(LedgerCommand.model_validate(command_values), identity)
    duplicate_values = dict(command_values, command_id="CMD-WP3-ALTERED-REDELIVERY")
    duplicate = executor.execute(LedgerCommand.model_validate(duplicate_values), identity)

    tenant_params = {"tenant": args.tenant}
    tenant_types = {"tenant": spanner.param_types.STRING}
    approvals = scalar(database, "SELECT COUNT(*) FROM Approvals WHERE tenant_id=@tenant",
                       tenant_params, tenant_types)
    receipts = scalar(database, "SELECT COUNT(*) FROM Receipts WHERE tenant_id=@tenant",
                      tenant_params, tenant_types)
    active = scalar(database, "SELECT COUNT(*) FROM PlanRevisions WHERE tenant_id=@tenant "
                    "AND revision='rev43' AND status='ACTIVE'", tenant_params, tenant_types)
    rerouted = scalar(database, "SELECT COUNT(*) FROM Orders WHERE tenant_id=@tenant "
                      "AND revision='rev43' AND order_id='O202' AND assigned_vehicle_id='TRUCK-02'",
                      tenant_params, tenant_types)
    pickup = scalar(database, "SELECT COUNT(*) FROM Orders WHERE tenant_id=@tenant "
                    "AND revision='rev43' AND order_id='O203' AND assigned_vehicle_id IS NULL "
                    "AND status='PARTNER_PICKUP_CONVERTED'", tenant_params, tenant_types)
    result = {
        "database": args.database, "tenant": args.tenant,
        "kms_key_version": envelope.kms_key_version,
        "first_receipt": first.receipt["receipt_id"],
        "duplicate_receipt": duplicate.receipt["receipt_id"],
        "duplicate_additional_mutations": duplicate.additional_mutations,
        "approval_count": approvals, "receipt_count": receipts,
        "active_repaired_revision_count": active, "rerouted_order_count": rerouted,
        "partner_pickup_count": pickup, "tamper_rejected": True, "expiry_rejected": True,
    }
    assert first.receipt["status"] == "SUCCESS" and first.additional_mutations == 3
    assert duplicate.idempotent_replay and duplicate.additional_mutations == 0
    assert first.receipt["receipt_id"] == duplicate.receipt["receipt_id"]
    assert approvals == receipts == active == rerouted == pickup == 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
