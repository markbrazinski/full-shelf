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

## Public health boundary acceptance

This is an acceptance-contract amendment, not a new runtime capability. The
current immutable deployment is the audit target, and its public Cloud Run
boundary has exactly one accepted externally reachable health endpoint:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  "${ORCHESTRATOR_URL}/"
# expected: 200

curl -sS -o /dev/null -w '%{http_code}\n' \
  "${ORCHESTRATOR_URL}/healthz"
# expected: 404
```

`GET /` without authentication returning HTTP 200 is the sole public health
success. The deployed `GET /healthz` response is a Google-generated HTTP 404 at
the Cloud Run platform boundary, before the container. Record that 404 as
`OBSERVED_LIVE` platform-boundary behavior; do not claim `/healthz` as an
observed-live application health endpoint.

The application's exhaustive route-authentication matrix still classifies
every registered route, including its internal `/healthz` route, and retains
default-deny behavior for unclassified paths. This amendment does not authorize
a replacement path, gateway, third service, deployment, IAM change, or weaker
authentication. All sensitive human, managed-callback, and internal-workload
routes remain subject to their verified-identity policies.

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
The WP2 replay is a structural isolated executor test. Its command trace and
`model_armor_correlation_id` are the same internally generated test value, and
its output says `managed_model_armor_invoked=false` with classification
`STRUCTURALLY_VERIFIED`. It is not managed Model Armor invocation evidence.

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

## One-login operator projection, SSE, and approval

Projection and SSE require the same Google-signed human GIS token as approval.
They do not accept the orchestrator workload identity. Start the bounded helper
with the deployment-bound OAuth client, exact allowlisted Mark subject, expected
verified email, isolated authority tenant, and operating day:

```bash
PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python scripts/bootstrap_wp3_operator.py \
  --client-id="${OPERATOR_OAUTH_CLIENT_ID}" \
  --allowed-subject="${ALLOWED_OPERATOR_SUBJECT}" \
  --expected-email="${ALLOWED_OPERATOR_EMAIL}" \
  --tenant-id=audit-final-canonical-20260814 \
  --operating-day=2026-08-14
```

The helper binds only `127.0.0.1`, applies GIS state and nonce checks, retains
the token only in process memory until expiry or explicit shutdown, and exposes
only canonical/altered approval, fixed authoritative projection, authenticated
SSE, and shutdown. It never displays the token. The SSE operation forwards
`Last-Event-ID` in a header and never places credentials or tenant scope in a
query parameter. Use the page controls, or while the helper is active run:

```bash
PYTHONPATH=packages/domain:packages/observability \
  .venv/bin/python scripts/watch_delta_sse.py \
  --tenant=audit-final-canonical-20260814 \
  --expect-no-event
```

The empty reserved projection must return empty authoritative arrays. SSE must
remain open and emit a server keep-alive; static beats are not acceptable. The
auditor must use the explicit shutdown control afterward. The builder does not
perform this positive GIS login or own the acceptance decision.

The single GIS login remains reserved for the independent auditor. With that
login, the auditor must still prove Mark's approval and KMS path, authenticated
projection access, authenticated SSE connection and cursor behavior, the fresh
reserved managed hero loop, and all remaining negative identity and mutation
controls. This runbook and its builder handoff do not declare backend
acceptance.

## Workload-only verifier controls

`scripts/qualify_delta_hero.py`, `scripts/verify_delta_graph.py`, and
`scripts/verify_deployed_model_armor.py` mint a memory-only Google-signed token
by impersonating only `full-shelf-orchestrator-sa`, with the exact orchestrator
audience. They no longer retrieve or send the retired judge API key. A human GIS
token must fail these internal routes, and the workload token must fail every
human route.
