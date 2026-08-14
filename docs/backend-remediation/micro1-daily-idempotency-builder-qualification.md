# Micro-Initiative 1 — ordinary operating-day builder qualification

Recorded: 2026-08-14  
Runtime commit: `08fd2fc25c91226224bdad6ab3cbd4174dce9ca8`  
Classification: builder testimony; independent daily-idempotency audit required

This record covers only ordinary operating-day creation and duplicate daily
Scheduler delivery. It is not backend acceptance. It did not exercise or
change next-day planning, the historical Pub/Sub backlog, human approval, KMS,
Cloud Tasks, SSE, Graph, Model Armor, ADK, or projections.

## Root cause

The rejected resolver derived a fresh authority tenant from the managed Pub/Sub
`messageId`. A second run of an unchanged daily Scheduler job therefore selected
a different authoritative tenant. The ledger mutation fingerprint also included
the transport message ID and publish time, which meant that stabilizing only the
tenant would have converted redelivery into an idempotency collision.

## Ordinary operating-day contract

`OperatingDayRequest` is the single product contract. Its stable identity is:

- logical tenant ID;
- ISO operating day;
- request type `PLAN_DAY_REQUESTED`;
- plan ID; and
- revision `rev07`.

The storage authority ID is deterministically `<logical-tenant>-<YYYYMMDD>` and
the external authority scope is `<logical-tenant>@<YYYY-MM-DD>`. Pub/Sub message
ID, publish time, audit profile, and random values do not participate. The
private ledger independently verifies both authority forms before mutation and
returns the original receipt when the complete stable command is replayed.

The existing schema already represents each day-scoped authority as an isolated
tenant-shaped scope. No schema migration, reset, reseed, or backfill was used.

## Runtime and verification

- `STRUCTURALLY_VERIFIED` — focused contract/domain/callback suite: 57 passed.
- `STRUCTURALLY_VERIFIED` — required plus Micro 1 scoped suite: 104 passed.
- `STRUCTURALLY_VERIFIED` — complete isolated suite: 180 passed, 21 warnings.
- `STRUCTURALLY_VERIFIED` — `git diff --check` passed before commit.
- `OBSERVED_LIVE` — orchestrator build
  `dd7d04a8-34a2-44d4-989a-7c0d83cbf1fc` succeeded from the exact runtime SHA.
- `OBSERVED_LIVE` — ledger build
  `2dfa0367-eaae-4025-a0bd-2579290c7587` succeeded from the same SHA.
- `OBSERVED_LIVE` — `full-shelf-orchestrator-00050-lzx` serves 100% from
  `sha256:2fca26163e04d2f9e8eb554c6563d5c0126081c6590fb46ca57b66fc2fb06913`.
- `OBSERVED_LIVE` — `full-shelf-plan-ledger-00025-rvr` serves 100% from
  `sha256:94b78ec3453374c8d382eb8e1a1f0399887371b80b131e65f14c9545d522b811`.
- `OBSERVED_LIVE` — exactly the same two Cloud Run services remain deployed.

## Qualification run 1 — 2026-08-16

Authority: `audit-canonical@2026-08-16`  
Storage tenant: `audit-canonical-20260816`  
Plan: `PLAN-AUDIT-CANONICAL/rev07`  
Stable receipt: `RCT-43BED3F7C91276B2BF1A6593`  
Stable key: `daily-plan:44edb2f3c3f3b4e2589fecc2`

- `OBSERVED_LIVE` — creation reached orchestrator and private ledger with HTTP
  200 on trace `da04d94fe4603db096629abbca1f8d87`; Spanner committed one
  tenant, one active rev07, and one receipt at `2026-08-14T20:46:13.955526Z`.
- `OBSERVED_LIVE` — the same unchanged job returned HTTP 200 again on both
  services at trace `04c48d562ba7db7af79156785c930a58`.
- `OBSERVED_LIVE` — a later zero-mutation replay was witnessed as Pub/Sub
  message `21015082371510489`, publish time `2026-08-14T20:50:32.553Z`, and
  HTTP 200 trace `0a05a3f95af0de601b39f8c97390e41d`.
- `MEASURED` — after all deliveries: one tenant, one rev07, one receipt, and
  zero approvals. The receipt ID, timestamp, original trace, and mutation count
  remained unchanged.
- `NOT_PROVEN` — the original creation publication's Pub/Sub message ID was not
  retained by Scheduler or Cloud Run request logging. The independently
  witnessed replay above proves message-level managed delivery without claiming
  that it was the original creation message.

## Qualification run 2 — 2026-08-17

Authority: `audit-canonical@2026-08-17`  
Storage tenant: `audit-canonical-20260817`  
Plan: `PLAN-AUDIT-CANONICAL/rev07`  
Stable receipt: `RCT-E70609ABE999E2A18E20BA83`  
Stable key: `daily-plan:868b3478290269d6cce3edc7`

- `OBSERVED_LIVE` — creation reached orchestrator and private ledger with HTTP
  200 on trace `ddda77e26070e76419f264fc9e2cfb4a`; Spanner committed one
  distinct tenant, one active rev07, and one receipt at
  `2026-08-14T20:48:50.745806Z`.
- `OBSERVED_LIVE` — the same unchanged job returned HTTP 200 again at trace
  `f9f8e70d39b698901226f129a3d735c8` with no count increase.
- `OBSERVED_LIVE` — a later zero-mutation replay was witnessed as Pub/Sub
  message `21437458139380413`, publish time `2026-08-14T20:51:05.254Z`, and
  HTTP 200 trace `304b236c4756cb14ff474edd158fd111`.
- `MEASURED` — after all deliveries: one tenant, one rev07, one receipt, and
  zero approvals. Day 17 is distinct from day 16 solely because its legitimate
  operating-day identity differs.
- `NOT_PROVEN` — as in run 1, the original creation publication's Pub/Sub
  message ID was not retained; only the later witnessed replay ID is claimed.

The temporary witness subscription was created after both creation sequences,
contained no historical messages, acknowledged only its two new copies, and was
deleted. It never read, sought, drained, or modified the existing push
subscription or its historical backlog. Attempts to create additional day-18
or day-19 authorities were rejected before execution; direct readback confirmed
zero such tenants.

## Canonical preservation and final managed state

- `MEASURED` — canonical `east-bay-food-bank` remains at exactly 17 receipts
  and zero approvals.
- `MEASURED` — both isolated Micro 1 authorities have one rev07, one receipt,
  and zero approvals.
- `OBSERVED_LIVE` — `full-shelf-delta-canonical-daily` is enabled, scheduled
  for `05:30 America/Los_Angeles`, targets `full-shelf-delta-audit`, and is left
  configured with the ordinary 2026-08-17 request.
- `STRUCTURALLY_VERIFIED` — no next-day code, migration, or third service was
  added.

## Exact targeted independent audit commands

Choose two unused ISO days after confirming that their deterministic authority
IDs do not exist. Use a unique witness name so the auditor observes only new
publications:

```bash
.venv/bin/python scripts/run_tests.py

micro1_day_one=YYYY-MM-DD
micro1_day_two=YYYY-MM-DD
micro1_witness=full-shelf-micro1-independent-witness

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud pubsub subscriptions create \
  "$micro1_witness" --topic=full-shelf-delta-audit \
  --project=preflight-hackathon --message-retention-duration=10m \
  --expiration-period=1d --ack-deadline=60

.venv/bin/python scripts/configure_operating_day_scheduler.py \
  --fixture=canonical --operating-day="$micro1_day_one"

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs describe \
  full-shelf-delta-canonical-daily --location=us-central1 \
  --project=preflight-hackathon --format=json

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs run \
  full-shelf-delta-canonical-daily --location=us-central1 \
  --project=preflight-hackathon
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud pubsub subscriptions pull \
  "$micro1_witness" --project=preflight-hackathon --limit=1 --auto-ack \
  --format='json(message.messageId,message.publishTime)'

# After the first HTTP 200 and direct Spanner readback, do not update the job.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs run \
  full-shelf-delta-canonical-daily --location=us-central1 \
  --project=preflight-hackathon
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud pubsub subscriptions pull \
  "$micro1_witness" --project=preflight-hackathon --limit=1 --auto-ack \
  --format='json(message.messageId,message.publishTime)'

# Replace YYYYMMDD with day one's compact date and verify 1 / 1 / 1 / 0.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-audit-wp6-20260813 --instance=fef-smoke-spanner \
  --project=preflight-hackathon \
  --sql="SELECT (SELECT COUNT(*) FROM Tenants WHERE tenant_id='audit-canonical-YYYYMMDD') AS tenants, (SELECT COUNT(*) FROM PlanRevisions WHERE tenant_id='audit-canonical-YYYYMMDD' AND revision='rev07') AS rev07s, (SELECT COUNT(*) FROM Receipts WHERE tenant_id='audit-canonical-YYYYMMDD') AS receipts, (SELECT COUNT(*) FROM Approvals WHERE tenant_id='audit-canonical-YYYYMMDD') AS approvals"

# Repeat configure/run/pull/run/pull/readback with $micro1_day_two.

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="full-shelf-orchestrator" AND httpRequest.status=200 AND httpRequest.userAgent:"APIs-Google"' \
  --project=preflight-hackathon --limit=20 --order=desc --format=json

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-main --instance=fef-smoke-spanner --project=preflight-hackathon \
  --sql="SELECT (SELECT COUNT(*) FROM Receipts WHERE tenant_id='east-bay-food-bank') AS receipts, (SELECT COUNT(*) FROM Approvals WHERE tenant_id='east-bay-food-bank') AS approvals"

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs describe \
  full-shelf-delta-canonical-daily --location=us-central1 \
  --project=preflight-hackathon --format='yaml(state,schedule,timeZone,pubsubTarget)'

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud pubsub subscriptions delete \
  "$micro1_witness" --project=preflight-hackathon --quiet
```

Builder qualification is complete. Independent reproduction must determine
acceptance.
