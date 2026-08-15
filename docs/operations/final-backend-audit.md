# Final backend audit operations

This runbook contains current operational commands only. Historical builder
evidence is not a source of implementation truth and is supplied to the final
auditor as an external archive.

## Fixed environment

- Project: `preflight-hackathon`
- Region: `us-central1`
- Spanner instance: `fef-smoke-spanner`
- Canonical database: `full-shelf-main`
- Isolated audit database: `full-shelf-audit-wp6-20260813`
- Logical final-audit tenant: `audit-final-canonical`
- Operating day: managed Pub/Sub `publishTime` converted to
  `America/Los_Angeles`; the reserved day is `2026-08-14`
- Storage authority: `audit-final-canonical-20260814`
- Daily job: `full-shelf-final-auditor-daily`
- Next-day job: `full-shelf-final-auditor-next-day`
- Daily plan: `PLAN-AUDIT-CANONICAL/rev07`, with governed repair at `rev08`
- Next-day plan: `PLAN-2026-08-15/rev01`
- Projection: `/api/v1/projections/demo-beats`
- SSE: `/api/v1/projections/stream`

The two jobs use ordinary production handlers and strict request schemas. Their
safe schedule is `0 0 1 1 *` in `Etc/UTC`; they must be enabled and have no
`lastAttemptTime` before the auditor deliberately runs them. Creating the job
definitions requires explicit authorization because enabled Scheduler resources
have persistent future-trigger effects. Never trigger them during preparation.

## Clean-shell local verification

Run from the repository root. No command depends on an activated virtual
environment or undeclared `PYTHONPATH`.

```bash
PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python -m pytest -q

PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python -m pytest -q \
  apps/orchestrator/tests/test_model_armor_halt.py \
  apps/orchestrator/tests/test_generalized_hero.py \
  apps/orchestrator/tests/test_sse_stream.py \
  packages/domain/tests/test_ledger_commands.py \
  packages/domain/tests/test_ledger_executor.py \
  packages/contracts/tests/test_locked_contracts.py

PYTHONPATH=packages/domain:packages/observability \
SPANNER_DATABASE_ID=full-shelf-audit-wp6-20260813 \
  .venv/bin/python scripts/verify_wp2_isolated.py
```

Do not run the isolated WP2 mutation replay against `full-shelf-main`.

## Reservation checks

Before any final-audit mutation, require 0 tenants, 0 plans, 0 receipts, and 0
approvals for the storage authority. Require canonical state to remain 18
receipts and 0 approvals.

```bash
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-audit-wp6-20260813 --instance=fef-smoke-spanner \
  --project=preflight-hackathon \
  --sql="SELECT (SELECT COUNT(*) FROM Tenants WHERE tenant_id='audit-final-canonical-20260814') AS tenants, (SELECT COUNT(*) FROM PlanRevisions WHERE tenant_id='audit-final-canonical-20260814') AS plans, (SELECT COUNT(*) FROM Receipts WHERE tenant_id='audit-final-canonical-20260814') AS receipts, (SELECT COUNT(*) FROM Approvals WHERE tenant_id='audit-final-canonical-20260814') AS approvals"

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-main --instance=fef-smoke-spanner --project=preflight-hackathon \
  --sql="SELECT (SELECT COUNT(*) FROM Receipts WHERE tenant_id='east-bay-food-bank') AS receipts, (SELECT COUNT(*) FROM Approvals WHERE tenant_id='east-bay-food-bank') AS approvals"
```

After explicit authorization, reserve the jobs without triggering them:

```bash
PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python scripts/configure_micro3_final_auditor.py

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs describe \
  full-shelf-final-auditor-daily --location=us-central1 \
  --project=preflight-hackathon \
  --format='yaml(name,state,schedule,timeZone,lastAttemptTime,pubsubTarget)'

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs describe \
  full-shelf-final-auditor-next-day --location=us-central1 \
  --project=preflight-hackathon \
  --format='yaml(name,state,schedule,timeZone,lastAttemptTime,pubsubTarget)'
```

## Authenticated projection and SSE

The projection verifier is bound to the existing Google-signed orchestrator
workload identity and exact orchestrator audience. The token remains in shell
memory and is neither printed nor written. This read-only reproduction requires
no Google login and creates no authoritative state.

```bash
audit_token=$(CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 \
  gcloud auth print-identity-token \
  --impersonate-service-account=full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com \
  --audiences=https://full-shelf-orchestrator-620464070103.us-central1.run.app \
  --include-email)

curl -sS -H "Authorization: Bearer ${audit_token}" \
  https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/projections/demo-beats

curl -sS -N --max-time 20 -H "Authorization: Bearer ${audit_token}" \
  https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/projections/stream

unset audit_token
```

The empty reserved projection must return empty authoritative arrays. The SSE
connection must remain open and emit a server keep-alive; static beats are not
acceptable. The auditor, not the builder, owns the subsequent managed hero loop
and acceptance decision.
