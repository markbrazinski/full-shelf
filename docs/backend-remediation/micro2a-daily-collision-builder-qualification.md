# Micro 2A — daily collision builder qualification

Recorded: 2026-08-14 (America/Los_Angeles)

Runtime commit: `01159471c8e8b5a28c98282a60b2cdb5ba7274e5`

Classification: builder testimony; resume independent Micro 2 audit

This record is limited to the daily-event `409 -> 502` retry storm and two
date-sensitive tests. It does not reopen accepted next-day behavior and does
not certify Micro 2. No receipt, plan, approval, subscription cursor, or other
canonical value was deleted, reset, compensated, or changed for this repair.

## 1. Collision root cause

The read-only reconstruction classified the event as a **genuine
changed-command/business-identity collision caused by a legacy identity
transition**, not an exact replay and not a malformed current job.

- `OBSERVED_LIVE` — Scheduler job `full-shelf-delta-canonical-daily` began the
  relevant attempt at `2026-08-15T00:44:58.478618Z` and published to
  `full-shelf-delta-audit`.
- `OBSERVED_LIVE` — Pub/Sub message `21016537566890825` carried the strict,
  date-free payload with keys `event_type=PLAN_DAY_REQUESTED`,
  `tenant_id=audit-canonical`, and `operating_plan`. The plan is the canonical
  audit fixture `PLAN-AUDIT-CANONICAL/rev07`, status `ACTIVE`; its custody,
  order, vehicle, and lot values are unchanged from
  `test-fixtures/audit_canonical_shaped.json`.
- `MEASURED` — verified publish time derived operating day `2026-08-14` in
  `America/Los_Angeles` and authority tenant
  `audit-canonical-20260814`.
- `STRUCTURALLY_VERIFIED` — the resulting ledger command was
  `CMD-DAY-467bbbcdf010957f2a3cc311`, type `SAVE_PLAN_REVISION`, expected
  revision `rev07`, incident `INC-DAY-467bbbcdf010957f2a3cc311`, and
  idempotency key `daily-plan:467bbbcdf010957f2a3cc311`. Its payload binds
  logical tenant `audit-canonical`, day `2026-08-14`, request type
  `PLAN_DAY_REQUESTED`, authority scope `audit-canonical-20260814`, and the
  complete submitted operating plan. Incoming request fingerprint:
  `b5c02450512d0e7f13043a82584f04090a8a19402dca4c5ef24d8d0e81f4501c`.
- `MEASURED` — the existing business identity was
  `PLAN-AUDIT-CANONICAL/rev07`, then `SUPERSEDED`. Its legacy receipt is
  `RCT-72D846D0DAD1DB7E115CFA37`, key
  `daily-plan:d3a3a94bcaed7d8fce827c41`, stored fingerprint `NULL`, original
  trace `d157cf9b4ef42fa1cef6ae45a5bb49c6`, and commit time
  `2026-08-14T05:48:56.191145Z`.
- `STRUCTURALLY_VERIFIED` — legacy identity hashed authority tenant, plan ID,
  and literal revision (`audit-canonical-20260814`,
  `PLAN-AUDIT-CANONICAL`, `rev07`). Its legacy payload also bound delivery
  source/message and publish time. The accepted current identity hashes logical
  tenant, operating day, request type, plan ID, and revision, excludes
  transport metadata, and explicitly records `logical_tenant_id`,
  `operating_day`, `request_type`, and `authority_scope`. These are the exact
  identity/payload differences; no product-plan field differed.
- `OBSERVED_LIVE` — representative pre-repair trace
  `468a2f85e7129e29340def070babf641` shows ledger revision
  `full-shelf-plan-ledger-00027-8q2` returned 409 and orchestrator revision
  `full-shelf-orchestrator-00053-6t4` returned 502. The old ledger exposed no
  bounded machine-readable collision object, so the daily orchestrator's
  general HTTP-error handler emitted
  `PLAN_LEDGER_DAILY_PLAN_COMMIT_FAILED`; the Pub/Sub handler therefore selected
  `RETRYABLE_FAILURE`.

The job and accepted daily identity were not rewritten. The collision is now a
visible, deterministic zero-mutation business rejection.

## 2. Ledger error contract

`STRUCTURALLY_VERIFIED` — `ledger_error.json` and plan-ledger OpenAPI now
define the permanent response:

```json
{
  "code": "IDEMPOTENCY_KEY_COLLISION",
  "category": "PERMANENT_BUSINESS_REJECTION",
  "retryable": false,
  "mutations_applied": 0,
  "collision_kind": "BUSINESS_IDENTITY_ALREADY_EXISTS"
}
```

The deterministic executor raises a typed `IdempotencyKeyCollision` for either
`FINGERPRINT_MISMATCH` or `BUSINESS_IDENTITY_ALREADY_EXISTS`. Exact key and
fingerprint matches still return the original receipt as an idempotent replay.
No general `ValueError`, unknown 409, or infrastructure exception receives this
contract.

## 3. Transport mapping

`STRUCTURALLY_VERIFIED` — daily Pub/Sub transport has a one-code allowlist:

- exact ledger replay -> HTTP 2xx with `IDEMPOTENT_REPLAY`;
- authenticated `IDEMPOTENCY_KEY_COLLISION` -> HTTP 2xx with
  `PERMANENTLY_REJECTED_ACKNOWLEDGED`, `mutations_applied=0`;
- authentication failure -> 401/403;
- unknown 409, network, timeout, availability, persistence, or other unknown
  failure -> HTTP 5xx `RETRYABLE_FAILURE`.

Logs now include message ID, trace ID, authority, error code, disposition, and
receipt ID or `NONE`. A transport acknowledgment is explicitly a rejected
business outcome, not mutation success. The previously accepted next-day
status mapping was preserved.

## 4. Test-clock repair

`STRUCTURALLY_VERIFIED` — `_utc_now()` is the callback clock seam. The two
stale-boundary tests freeze it at `2026-08-14T00:31:00Z` around a
`2026-08-14T00:30:00Z` publish time; no fixed historical time is compared with
the real wall clock.

- Previously failing selection: 72 passed, 5 warnings.
- Focused repair selection: 78 passed, 9 warnings.
- Complete isolated suite: 200 passed, 21 warnings.
- Focused transient regression after deployment work: 2 passed, 3 warnings.

## 5. Runtime commit and deployment

- Commit: `01159471c8e8b5a28c98282a60b2cdb5ba7274e5`
  (`fix(events): acknowledge deterministic daily collisions`).
- `OBSERVED_LIVE` — orchestrator build
  `9949d8f0-bb90-4a86-8820-78f74c306ca5` produced
  `sha256:f34342a0ce42bf213a8d3b6e1536dbaaf72a9e11716ef6a988174df092116ea5`.
- `OBSERVED_LIVE` — ledger build
  `172e98c1-63e9-4727-9d91-e8463f4f784f` produced
  `sha256:422f5e52f53858efcf48bc65c8578605df7421ca6af771cff633940ce6efe80d`.
- `OBSERVED_LIVE` — `full-shelf-orchestrator-00054-ptt` and
  `full-shelf-plan-ledger-00028-kdn` each serve 100% from those immutable
  digests. Exactly two Full Shelf Cloud Run services exist.
- `OBSERVED_LIVE` — deployment initially removed a prior public orchestrator
  invoker binding. Pub/Sub therefore received Cloud Run edge 403s until the
  narrow expected callback service account received `roles/run.invoker` on
  the orchestrator; the same principal-only binding remains on the private
  ledger. Public access was not restored. This deployment event is kept in the
  qualification record rather than hidden.
- No OAuth login was requested or performed.

## 6. Existing-message convergence

- `OBSERVED_LIVE` — retained message `21016537566890825` reached revision
  `full-shelf-orchestrator-00054-ptt` at
  `2026-08-15T01:09:53.526981Z`.
- `OBSERVED_LIVE` — trace `ab4d0a4ee01d947c36d6eda9e6ac08bc` shows
  ledger 409 on revision `00028-kdn` and orchestrator 200 on revision
  `00054-ptt`.
- `OBSERVED_LIVE` — disposition was
  `PERMANENTLY_REJECTED_ACKNOWLEDGED`, authority
  `audit-canonical-20260814`, error `IDEMPOTENCY_KEY_COLLISION`, receipt
  `NONE`.
- `MEASURED` — direct readback remained one tenant, three revisions, fifteen
  receipts, one approval, and zero receipts for incoming key
  `daily-plan:467bbbcdf010957f2a3cc311`.

The retained message left the subscription naturally; no purge, seek,
recreation, or mutation was used.

## 7. Fresh collision qualification

- `MEASURED` — immediate pre-trigger isolated state was 15 receipts, one
  approval, three revisions, and zero receipts for the incoming key; canonical
  state was 18/0.
- `OBSERVED_LIVE` — the required single manual run of
  `full-shelf-delta-canonical-daily` began at
  `2026-08-15T01:10:43.555877Z` and produced new message
  `21016153342747470`.
- `OBSERVED_LIVE` — after the deployment IAM binding propagated, its first
  authenticated application delivery completed at
  `2026-08-15T01:14:02.618693Z` on trace
  `31f9fd6c966ad0a100d3736c4d95afef`: ledger 409, orchestrator 200,
  `PERMANENTLY_REJECTED_ACKNOWLEDGED`, the expected authority and error code,
  and receipt `NONE`.
- `MEASURED` — post-delivery isolated state remained exactly 15/1/3 and zero
  incoming-key receipts.

The message did receive Cloud Run edge 403 retries while the narrow invoker
binding propagated. It did not retry after the terminal application 2xx, and
no current-revision application retry storm followed. This is a deployment
qualification caveat for the independent auditor; it is not represented as a
collision-handler retry.

## 8. Valid daily and next-day regressions

`OBSERVED_LIVE` — accepted Micro 1 job `full-shelf-micro1a-builder-daily`
produced message `21017194561139037`. Trace
`594e2f89a2eaf766a377b23acad393e9` returned orchestrator/ledger 200/200 and
`IDEMPOTENT_REPLAY` with original receipt `RCT-6398D07037DB7A62743F70D5`.
`MEASURED` readback remained one tenant, one rev07, one receipt, zero
approvals; receipt key, fingerprint, original trace, and commit time were
unchanged.

`OBSERVED_LIVE` — one accepted `full-shelf-next-day-plan-job` run produced
message `21019132565933830`. The two pre-existing subscriptions delivered it on
traces `69251bd972e16973616b14331c3ae346` and
`f67910553bd36e404c6f5e1850310c2f`; both paths returned
orchestrator/ledger 200/200 and `IDEMPOTENT_REPLAY` with
`RCT-F2C376A7B99D15C2C66A9033`. `MEASURED` direct readback preserved its key
`east-bay-food-bank:PLAN-2026-08-15:rev01:day-close`, fingerprint
`86323afb10f926461dfb87ffed39d0129ab12b3eae6bc79f47acd7abc4b6f9ce`,
original trace, commit time, and canonical 18/0.

## 9. Transient-failure regression

`STRUCTURALLY_VERIFIED` — fault-injected daily authoritative persistence 503
and next-day authoritative continuity-read 503 both remain HTTP 503 at the
Pub/Sub boundary (`2 passed`). No production fault switch exists, so this is
not claimed as an observed live outage. Unknown ledger 409 and unparseable
ledger error tests also remain 5xx.

## 10. Backlog and canonical preservation

- `MEASURED` — Cloud Monitoring reported zero undelivered messages at 01:17,
  01:18, and 01:19 UTC for all three subscriptions:
  `full-shelf-delta-audit-push`, `full-shelf-incidents-sub`, and
  `full-shelf-next-day-plan-sub`.
- `OBSERVED_LIVE` — no HTTP status >=400 occurred on orchestrator revision
  `00054-ptt` from `2026-08-15T01:14:03Z` through the recorded quiet-window
  query. No current-revision retry storm remained.
- `MEASURED` — final canonical readback remained 18 receipts and zero
  approvals. Receipt `RCT-F2C376A7B99D15C2C66A9033` was not modified.

## 11. Auditor reproduction commands

Reserved job `full-shelf-micro2a-auditor-collision-daily` is enabled at
`30 5 * * *`, `America/Los_Angeles`, and has no `lastAttemptTime`. The builder
did not trigger it. Before local midnight on 2026-08-14 it derives the existing
collision authority `audit-canonical-20260814`; at a later audit date, first
capture that date's baseline and use the standing canonical job only where an
existing same-day business identity has already been established.

```bash
audit_start=$(date -u +%Y-%m-%dT%H:%M:%SZ)

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs describe \
  full-shelf-micro2a-auditor-collision-daily --location=us-central1 \
  --project=preflight-hackathon \
  --format='yaml(name,state,schedule,timeZone,lastAttemptTime,userUpdateTime)'

# Capture isolated and canonical baselines immediately before testing.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-audit-wp6-20260813 --instance=fef-smoke-spanner \
  --project=preflight-hackathon \
  --sql="SELECT (SELECT COUNT(*) FROM Receipts WHERE tenant_id='audit-canonical-20260814') AS receipts, (SELECT COUNT(*) FROM Approvals WHERE tenant_id='audit-canonical-20260814') AS approvals"
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-main --instance=fef-smoke-spanner --project=preflight-hackathon \
  --sql="SELECT (SELECT COUNT(*) FROM Receipts WHERE tenant_id='east-bay-food-bank') AS receipts, (SELECT COUNT(*) FROM Approvals WHERE tenant_id='east-bay-food-bank') AS approvals"

# Trigger exactly once; this is intentionally a rejected business command.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud scheduler jobs run \
  full-shelf-micro2a-auditor-collision-daily --location=us-central1 \
  --project=preflight-hackathon

# Require one new message with terminal 2xx, the explicit collision code,
# receipt NONE, and no later delivery of that message ID.
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud logging read \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"full-shelf-orchestrator\" AND timestamp>=\"${audit_start}\"" \
  --project=preflight-hackathon --limit=100 --order=asc \
  --format='json(timestamp,httpRequest.status,textPayload,trace,resource.labels.revision_name)'

# Repeat both baseline reads; require exact equality and canonical 18/0.
# Also require zero for every subscription without purge, seek, or recreation.
```

Future preservation checks use a baseline captured immediately before testing,
pre-identify expected managed transitions, and reject any unexplained or
unauthorized delta. They do not treat a standing control plane's receipt count
as permanently fixed.
