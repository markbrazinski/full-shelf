#!/usr/bin/env python3
"""Execute V6.3 SQL and transaction paths against an isolated Spanner emulator.

Requires SPANNER_EMULATOR_HOST and explicit --database/--tenant arguments. The
script refuses a missing emulator endpoint and never creates, resets, or reads a
canonical database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from google.adk.models.llm_response import LlmResponse
from google.auth.credentials import AnonymousCredentials
from google.cloud import spanner
from google.genai import types

from full_shelf_domain.identity import VerifiedGoogleIdentity
from full_shelf_domain.ledger_commands import LedgerCommand
from full_shelf_domain.ledger_executor import SpannerLedgerCommandExecutor
from full_shelf_domain.partner_evidence import (
    PartnerCustodyConfirmationDetails,
    partner_evidence_prompt,
    run_partner_evidence_agent,
    source_sha256,
)


DAY = "2026-08-14"
INCIDENT = "INC-V63-EMULATOR"
WORK = "WORK-PCF-V63-EMULATOR"
PARTNER = "PARTNER-AGENCY-01"


def _proposal(complete: bool) -> dict:
    base = {
        "incident_id": INCIDENT, "partner_id": PARTNER, "site_id": "SITE-01",
        "custody_node_id": "N-ST01", "work_item_id": WORK,
        "expected_acknowledgment_status": "UNCONFIRMED",
        "requested_acknowledgment_status": "CONFIRMED",
        "lot": None, "quantity": None, "location": None, "disposition": None,
        "confirmation_time": None, "requested_mutation": "CONFIRM_CUSTODY",
        "rationale": "Missing required evidence." if not complete else "All required evidence is anchored.",
        "confidence": 0.75 if not complete else 0.99,
    }
    if complete:
        base.update({
            "lot": {"value": "LTC-4471", "quote": "LTC-4471"},
            "quantity": {"value": 8, "quote": "8 cases"},
            "location": {"value": "Site 01", "quote": "Site 01"},
            "disposition": {"value": "ISOLATED_IN_QUARANTINE",
                            "quote": "ISOLATED_IN_QUARANTINE"},
            "confirmation_time": {"value": "10:18", "quote": "confirmed at 10:18"},
        })
    return base


async def _real_adk_execution(proposal: dict, source_text: str):
    from google.adk.models.google_llm import Gemini

    async def fake_generate(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content(
            role="model", parts=[types.Part.from_text(text=json.dumps(proposal))]
        ))

    with patch.object(Gemini, "generate_content_async", fake_generate):
        return await run_partner_evidence_agent(partner_evidence_prompt(
            source_text=source_text,
            authority={
                "incident_id": INCIDENT, "partner_id": PARTNER,
                "site_id": "SITE-01", "custody_node_id": "N-ST01",
                "work_item_id": WORK, "lot_id": "LTC-4471", "expected_cases": 8,
            },
        ))


def _seed(database, tenant: str):
    details = PartnerCustodyConfirmationDetails(
        schema_version="partner-custody-confirmation.v1", partner_id=PARTNER,
        site_id="SITE-01", custody_node_id="N-ST01", lot_id="LTC-4471",
        expected_cases=8, expected_acknowledgment_status="UNCONFIRMED",
        requested_acknowledgment_status="CONFIRMED",
        hold_incident_id="HOLD-V63-EMULATOR", operating_day=DAY,
        source_task_name="emulator/tasks/v63",
    )
    with database.batch() as batch:
        batch.insert("Tenants", ["tenant_id", "name", "created_at"],
                     [[tenant, "V6.3 emulator tenant", spanner.COMMIT_TIMESTAMP]])
        batch.insert("PlanRevisions",
                     ["tenant_id", "plan_id", "revision", "status", "created_at"],
                     [[tenant, f"PLAN-{DAY}", "rev08", "INVALIDATED_RECALL",
                       spanner.COMMIT_TIMESTAMP]])
        batch.insert("Incidents", [
            "tenant_id", "incident_id", "parent_coordinator_id", "incident_type",
            "status", "affected_lot_id", "created_at", "details", "terminal_state",
        ], [[tenant, INCIDENT, "COORD-V63", "FOOD_SAFETY_RECALL",
             "PARTIALLY_CONTAINED", "LTC-4471", spanner.COMMIT_TIMESTAMP, "{}",
             "PARTIALLY_CONTAINED"]])
        batch.insert("WorkItems", [
            "tenant_id", "work_item_id", "incident_id", "work_type", "status",
            "details", "created_at",
        ], [[tenant, WORK, INCIDENT, "PARTNER_CUSTODY_CONFIRMATION", "OPEN",
             details.model_dump_json(), spanner.COMMIT_TIMESTAMP]])
        batch.insert("CustodyNodes", [
            "tenant_id", "node_id", "node_type", "name", "on_hand_cases",
            "acknowledgment_status",
        ], [
            [tenant, "N-WH", "WAREHOUSE", "Confirmed network positions", 88, "CONFIRMED"],
            [tenant, "N-ST01", "SUBSITE", "Site 01", 8, "UNCONFIRMED"],
        ])
        batch.insert("CustodyEdges", [
            "tenant_id", "edge_id", "source_node_id", "target_node_id", "lot_id",
            "case_count", "is_sub_distribution",
        ], [[tenant, "E-ST01", "N-WH", "N-ST01", "LTC-4471", 8, True]])


def _command(*, tenant: str, source_event_id: str, source_text: str,
             proposal, adk, occurred_at: str) -> LedgerCommand:
    return LedgerCommand.model_validate({
        "command_id": f"CMD-{source_event_id}",
        "idempotency_key": f"partner-evidence:{source_event_id}",
        "tenant_id": tenant, "incident_id": INCIDENT,
        "agent_role": "PARTNER_OPERATIONS_AGENT",
        "command_type": "PROCESS_PARTNER_EVIDENCE",
        "expected_plan_revision": "rev08",
        "trace_id": "0123456789abcdef0123456789abcdef",
        "payload": {
            "event_type": "PARTNER_CUSTODY_EVIDENCE_RECEIVED",
            "source_event_id": source_event_id, "operating_day": DAY,
            "source_occurred_at": occurred_at, "source_text": source_text,
            "source_sha256": source_sha256(source_text), "partner_id": PARTNER,
            "callback_subject": "emulator-partner-subject",
            "callback_email": "partner@example.com",
            "callback_audience": "https://orchestrator.example/partner-evidence",
            "callback_issuer": "https://accounts.google.com",
            "callback_provenance": "AUTHENTICATED_PARTNER_CALLBACK",
            "model_armor": {"status": "APPROVED", "safety_verdict": "PASSED",
                            "managed_operation": "sanitizeUserPrompt"},
            "proposal": proposal.model_dump(mode="json"), **adk,
        },
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="full-shelf-v63-emulator")
    parser.add_argument("--instance", default="full-shelf-v63")
    parser.add_argument("--database", required=True)
    parser.add_argument("--tenant", required=True)
    args = parser.parse_args()
    if not os.getenv("SPANNER_EMULATOR_HOST"):
        raise SystemExit("SPANNER_EMULATOR_HOST_REQUIRED")
    if args.database == "full-shelf-main":
        raise SystemExit("CANONICAL_DATABASE_FORBIDDEN")

    client = spanner.Client(project=args.project, credentials=AnonymousCredentials())
    database = client.instance(args.instance).database(args.database)
    _seed(database, args.tenant)
    executor = SpannerLedgerCommandExecutor(database, allowed_tenant_ids={args.tenant})
    identity = VerifiedGoogleIdentity(
        subject="orchestrator-workload", email="orchestrator@example.com",
        audience="https://ledger", issuer="https://accounts.google.com",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    vague_text = "We pulled the remaining lettuce. Should be all good."
    vague_proposal, vague_adk = asyncio.run(_real_adk_execution(
        _proposal(False), vague_text
    ))
    vague = executor.execute(_command(
        tenant=args.tenant, source_event_id="partner-vague", source_text=vague_text,
        proposal=vague_proposal, adk=vague_adk,
        occurred_at="2026-08-14T10:15:00+00:00",
    ), identity)
    assert vague.receipt["status"] == "DENIED"
    assert vague.receipt["mutations_applied"] == 0
    replay = executor.execute(_command(
        tenant=args.tenant, source_event_id="partner-vague", source_text=vague_text,
        proposal=vague_proposal, adk=vague_adk,
        occurred_at="2026-08-14T10:15:00+00:00",
    ), identity)
    assert replay.idempotent_replay and replay.additional_mutations == 0

    complete_text = (
        "LTC-4471 · 8 cases · ISOLATED_IN_QUARANTINE at Site 01 · confirmed at 10:18."
    )
    complete_proposal, complete_adk = asyncio.run(_real_adk_execution(
        _proposal(True), complete_text
    ))
    complete = executor.execute(_command(
        tenant=args.tenant, source_event_id="partner-complete",
        source_text=complete_text, proposal=complete_proposal, adk=complete_adk,
        occurred_at="2026-08-14T10:18:00+00:00",
    ), identity)
    assert complete.receipt["status"] == "SUCCESS"
    assert complete.receipt["mutations_applied"] == 2

    with database.snapshot(multi_use=True) as snapshot:
        counts = list(snapshot.execute_sql(
            "SELECT acknowledgment_status, SUM(on_hand_cases) FROM CustodyNodes "
            "WHERE tenant_id=@tenant GROUP BY acknowledgment_status",
            params={"tenant": args.tenant},
            param_types={"tenant": spanner.param_types.STRING},
        ))
        work = list(snapshot.execute_sql(
            "SELECT status FROM WorkItems WHERE tenant_id=@tenant AND work_item_id=@work",
            params={"tenant": args.tenant, "work": WORK},
            param_types={"tenant": spanner.param_types.STRING,
                         "work": spanner.param_types.STRING},
        ))
        evidence = list(snapshot.execute_sql(
            "SELECT policy_decision, domain_mutations_applied, evidence_mutations_applied, "
            "adk_invocation_id, receipt_id FROM PartnerEvidenceEvents "
            "WHERE tenant_id=@tenant ORDER BY committed_at",
            params={"tenant": args.tenant},
            param_types={"tenant": spanner.param_types.STRING},
        ))
        receipts = list(snapshot.execute_sql(
            "SELECT receipt_id, status, mutations_applied, evidence_mutations_applied "
            "FROM Receipts WHERE tenant_id=@tenant ORDER BY timestamp",
            params={"tenant": args.tenant},
            param_types={"tenant": spanner.param_types.STRING},
        ))
    assert [tuple(row) for row in counts] == [("CONFIRMED", 96)]
    assert [tuple(row) for row in work] == [("COMPLETED",)]
    assert [(row[0], row[1], row[2]) for row in evidence] == [
        ("DENIED", 0, 1), ("APPLIED", 2, 1)
    ]
    assert all(row[3] and row[4] for row in evidence)
    assert len(receipts) == 2
    assert {row[0] for row in receipts} == {row[4] for row in evidence}
    print(json.dumps({
        "database": args.database, "tenant": args.tenant,
        "vague": {"status": vague.receipt["status"], "confirmed_cases": 88,
                  "work_item": "OPEN", "domain_mutations": 0},
        "complete": {"status": complete.receipt["status"], "confirmed_cases": 96,
                     "work_item": "COMPLETED", "domain_mutations": 2},
        "receipts": len(receipts), "evidence_rows": len(evidence),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
