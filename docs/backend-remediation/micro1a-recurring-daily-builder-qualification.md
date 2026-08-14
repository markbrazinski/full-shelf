# Micro-Initiative 1A — recurring-daily builder qualification

Recorded: 2026-08-14  
Runtime commit: `db3949de770067dc8f5259d14c587436f951645a`  
Classification: builder testimony; independent daily-idempotency audit required

This record is limited to recurring ordinary operating-day creation. It is not
backend acceptance. It does not reopen next-day planning, the historical
Pub/Sub backlog, approval, KMS, Tasks, SSE, Graph, Model Armor, ADK, or
projection behavior.

## Recurring-daily root cause and contract

The ledger-side `OperatingDayRequest` was stable only after an explicit ISO day
was supplied, while the standing Scheduler definitions embedded fixed days.
Those jobs could replay one configured day but could not operate daily without
manual edits.

Scheduler now publishes the strict, date-free `RecurringDailyRequest`:

- `event_type=PLAN_DAY_REQUESTED`;
- one configured logical `tenant_id`; and
- the ordinary `operating_plan` at `rev07`.

After Google workload OIDC verification, the orchestrator parses managed
Pub/Sub `message.publishTime`, converts it to `America/Los_Angeles`, and passes
only the resulting ISO date into the preserved `OperatingDayRequest`. Ledger
identity remains logical tenant, ISO day, request type, plan ID, and revision.
Raw publish time, Pub/Sub message ID, trace ID, request ID, and delivery attempt
do not enter the command payload, idempotency key, or request fingerprint.

## Runtime and structural verification

- `STRUCTURALLY_VERIFIED` — required plus scoped suite: 112 passed.
- `STRUCTURALLY_VERIFIED` — complete isolated regression suite: 188 passed,
  21 warnings.
- `STRUCTURALLY_VERIFIED` — focused managed-time/idempotency suite: 4 passed.
- `STRUCTURALLY_VERIFIED` — `06:59:59Z` on 2026-08-15 derives 2026-08-14
  in Los Angeles; `07:00:00Z` derives 2026-08-15.
- `STRUCTURALLY_VERIFIED` — caller-supplied `operating_day` and timestamp are
  rejected, and distinct delivery IDs produce the same same-day ledger command.
- `OBSERVED_LIVE` — orchestrator build
  `2bf81a28-e6eb-4806-879f-e8fc3e29308a` produced
  `sha256:1552554d31712fcfd0d5ec7939d0fb822bcb3d333fb83e60dcf564b0560fd7f9`.
- `OBSERVED_LIVE` — ledger build
  `4998d714-163a-4782-b057-da34fca33ce9` produced
  `sha256:04da09ef868bdbe662f2ac1972e563baa929625c3ef5ea62121f30e1422eb5f6`.
- `OBSERVED_LIVE` — `full-shelf-orchestrator-00051-bwl` and
  `full-shelf-plan-ledger-00026-gn8` each serve 100% from those digests.
- `OBSERVED_LIVE` — exactly those two Full Shelf Cloud Run services remain.

## Builder same-day replay

Builder job: `full-shelf-micro1a-builder-daily`  
Logical tenant: `audit-canonical-builder-m1a`  
Derived day: `2026-08-14`  
Authority tenant: `audit-canonical-builder-m1a-20260814`  
Plan: `PLAN-AUDIT-CANONICAL/rev07`

First delivery:

- `OBSERVED_LIVE` — Pub/Sub message `21437631378193705`, published
  `2026-08-14T21:45:42.453Z`.
- `OBSERVED_LIVE` — orchestrator and private ledger both returned HTTP 200 on
  trace `6319249ea0ddffb0e9302b10cbcf608f`.
- `MEASURED` — receipt `RCT-6398D07037DB7A62743F70D5`, key
  `daily-plan:cee2e97b0a6c8f2da2871c36`, fingerprint
  `ed10683eeb52707ce1a1f43c868f63949d818639b569c496ad05c845b330473f`,
  and commit time `2026-08-14 14:45:47.094382-07`.

Unchanged duplicate delivery:

- `OBSERVED_LIVE` — distinct Pub/Sub message `21016747697531582`, published
  `2026-08-14T21:46:27.814Z`.
- `OBSERVED_LIVE` — orchestrator and private ledger both returned HTTP 200 on
  trace `2fecf2b4c9222aa3755e2693dbc3940c`.
- `MEASURED` — direct post-replay readback remained exactly one tenant, one
  rev07, one receipt, and zero approvals. Receipt ID, key, fingerprint,
  original trace, commit time, and mutation count were unchanged.

The fresh witness subscription received only these two post-creation messages,
acknowledged them, and was deleted. It did not read or alter any historical
subscription backlog.

## Scheduler migration and auditor reserves

`OBSERVED_LIVE` — all ordinary daily jobs are enabled at
`30 5 * * *`, `America/Los_Angeles`, and every decoded payload contains exactly
`event_type`, `tenant_id`, and `operating_plan`:

- `full-shelf-daily-plan-job` — `east-bay-food-bank`;
- `full-shelf-delta-canonical-daily` — `audit-canonical`;
- `full-shelf-delta-altered-daily` — `audit-altered`;
- `full-shelf-micro1a-builder-daily` — builder-only tenant;
- `full-shelf-micro1a-auditor-canonical-daily` — reserved tenant
  `audit-canonical-auditor-a`; and
- `full-shelf-micro1a-auditor-altered-daily` — reserved tenant
  `audit-altered-auditor-b`.

`OBSERVED_LIVE` — both reserved jobs are enabled, have no `lastAttemptTime`,
and were not triggered by the builder. `MEASURED` — their 2026-08-14 authority
tenants, receipts, and approvals are all zero. If manually run before local
midnight on 2026-08-14 they derive `2026-08-14`; their next natural scheduled
run at 05:30 on 2026-08-15 derives `2026-08-15` without configuration changes.

## Canonical preservation

`MEASURED` — canonical `east-bay-food-bank` remains exactly 17 receipts and
zero approvals after deployment, migration, and both builder deliveries. No
schema migration, reset, reseed, or backfill was performed.

## Exact independent reproduction commands

These commands do not update either reserved job. Run the replay twice before
local midnight, or substitute the local date naturally current at audit time.

```bash
.venv/bin/python scripts/run_tests.py

audit_job=full-shelf-micro1a-auditor-canonical-daily
audit_tenant=audit-canonical-auditor-a
audit_day=$(TZ=America/Los_Angeles date +%F)
audit_compact=$(printf '%s' "$audit_day" | tr -d '-')
audit_authority="${audit_tenant}-${audit_compact}"
audit_witness=full-shelf-micro1a-independent-witness

# Confirm ENABLED, 05:30 America/Los_Angeles, and inspect userUpdateTime.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs describe \
  "$audit_job" --location=us-central1 --project=preflight-hackathon \
  --format='yaml(name,state,schedule,timeZone,scheduleTime,lastAttemptTime,userUpdateTime,status)'

# Confirm the payload has no operating_day, qualification_profile, or timestamp.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs describe \
  "$audit_job" --location=us-central1 --project=preflight-hackathon \
  --format='value(pubsubTarget.data)' | base64 -d | jq \
  '{keys:(keys|sort),tenant_id,event_type,plan_id:.operating_plan.plan_id,revision:.operating_plan.revision}'

# Confirm the day-scoped authority is unused before triggering.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-audit-wp6-20260813 --instance=fef-smoke-spanner \
  --project=preflight-hackathon \
  --sql="SELECT (SELECT COUNT(*) FROM Tenants WHERE tenant_id='${audit_authority}') AS tenants, (SELECT COUNT(*) FROM PlanRevisions WHERE tenant_id='${audit_authority}' AND revision='rev07') AS rev07s, (SELECT COUNT(*) FROM Receipts WHERE tenant_id='${audit_authority}') AS receipts, (SELECT COUNT(*) FROM Approvals WHERE tenant_id='${audit_authority}') AS approvals"

# The new witness starts with no historical messages.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud pubsub subscriptions create \
  "$audit_witness" --topic=full-shelf-delta-audit \
  --project=preflight-hackathon --message-retention-duration=10m \
  --expiration-period=1d --ack-deadline=60

# First managed Scheduler -> Pub/Sub -> orchestrator -> ledger delivery.
audit_log_start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs run \
  "$audit_job" --location=us-central1 --project=preflight-hackathon
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud pubsub subscriptions pull \
  "$audit_witness" --project=preflight-hackathon --limit=1 --auto-ack \
  --format='json(message.messageId,message.publishTime)'

# Run the exact unchanged job again on the same local day.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs run \
  "$audit_job" --location=us-central1 --project=preflight-hackathon
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud pubsub subscriptions pull \
  "$audit_witness" --project=preflight-hackathon --limit=1 --auto-ack \
  --format='json(message.messageId,message.publishTime)'

# Require 1 / 1 / 1 / 0 and record the stable receipt, key, fingerprint, and trace.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-audit-wp6-20260813 --instance=fef-smoke-spanner \
  --project=preflight-hackathon \
  --sql="SELECT r.receipt_id, r.plan_revision_id, r.idempotency_key, r.request_fingerprint, r.trace_id, CAST(r.timestamp AS STRING) AS committed_at, (SELECT COUNT(*) FROM Tenants t WHERE t.tenant_id=r.tenant_id) AS tenants, (SELECT COUNT(*) FROM PlanRevisions p WHERE p.tenant_id=r.tenant_id AND p.revision='rev07') AS rev07s, (SELECT COUNT(*) FROM Receipts rr WHERE rr.tenant_id=r.tenant_id) AS receipts, (SELECT COUNT(*) FROM Approvals a WHERE a.tenant_id=r.tenant_id) AS approvals FROM Receipts r WHERE r.tenant_id='${audit_authority}'"

# Require managed Pub/Sub HTTP 200 entries and corresponding private-ledger 200s.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud logging read \
  "resource.type=\"cloud_run_revision\" AND timestamp>=\"${audit_log_start}\" AND httpRequest.status=200" \
  --project=preflight-hackathon --limit=50 --order=desc \
  --format='json(timestamp,resource.labels.service_name,resource.labels.revision_name,httpRequest.status,httpRequest.userAgent,trace)'

# Canonical state must remain 17 / 0.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-main --instance=fef-smoke-spanner --project=preflight-hackathon \
  --sql="SELECT (SELECT COUNT(*) FROM Receipts WHERE tenant_id='east-bay-food-bank') AS receipts, (SELECT COUNT(*) FROM Approvals WHERE tenant_id='east-bay-food-bank') AS approvals"

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud pubsub subscriptions delete \
  "$audit_witness" --project=preflight-hackathon --quiet
```

The second reserved job is independently available as
`full-shelf-micro1a-auditor-altered-daily`; its configured logical tenant is
`audit-altered-auditor-b`. Builder qualification does not constitute acceptance.
