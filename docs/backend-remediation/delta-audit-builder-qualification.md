# Backend delta-audit builder qualification

Date: 2026-08-14  
Branch: `repair/backend-delta-audit-20260814`  
Classification: builder testimony; independent reproduction is required  

This record covers only the bounded failures in the 2026-08-14 independent
audit. It does not certify acceptance and does not modify or backfill shared
canonical authority.

## Repair-package status

| Package | Commit | Safe tests | Deployed qualification | Remaining blocker |
| --- | --- | --- | --- | --- |
| A — isolated authority | `52fc47e` | Included in 165-pass suite | Both configured audit tenants resolved to the audit database through normal routes | None |
| B — human approval/KMS | `92b2043` | Negative identity, binding, expiry, tamper, replay, and ordering coverage | Real allowlisted GIS login; one approval then one activation per tenant | None |
| C — Scheduler/Pub/Sub | `c52d790` | Delivery, schema, and idempotency coverage | Daily and next-day managed deliveries returned 200; one stable receipt per operation | Legacy shared subscription backlog remains a recorded operational limitation |
| D — Cloud Tasks | `9b8ba0a` | OIDC, scoping, duplicate-name, and callback idempotency coverage | One fresh managed callback and stable receipt per hero loop | None |
| E — live SSE | `0035a55` | Durable cursor and malformed-cursor coverage | Approval receipt arrived after connection once for each tenant; cursor reconnect emitted zero duplicates | None |
| F — generalized hero | `05b7099` | Canonical-shaped and altered policy tests | Both isolated managed loops completed through the same implementation | None |
| G — contracts | `3b8c3db` | Contract-driven lifecycle, events, and full-envelope tests | Deployed runtime uses the corrected command contracts | None |
| H — Model Armor durability | `e2e7001` | 403, timeout, malformed/partial response, failed/skipped filter, and unsupported-version adapter tests | Managed benign/injection/URI/dangerous controls used Filter v3 via `FILTER_VERSION_ALIAS_LATEST` | None |

Complete safe suite: **165 collected, 165 passed, 0 failed, 0 skipped, 21
warnings in 3.61 seconds**. Command: `.venv/bin/python scripts/run_tests.py`.
The warnings are the already-recorded Cloud Trace exporter, FastAPI lifecycle,
Google GenAI typing, and Google Cloud Storage compatibility warnings.

## Root causes and closure

The failed daily job supplied only an event type and tenant while the old route
constructed a canonical, partial plan and sent it through a command contract
that did not own all required relational inputs. The ledger denial was wrapped
as orchestrator HTTP 502. The repair makes `OperatingPlanDefinition` a strict
contract, carries the complete plan in the Scheduler/Pub/Sub event, and derives
the command and idempotency key from tenant, plan, and revision. Invalid old
payloads now fail explicitly at validation; valid duplicates return the stable
ledger result.

The mixed next-day responses came from evaluating `expected_plan_revision`
only against the active revision. A correct recall invalidates rev08, so a
post-recall day-close could be denied even though `INVALIDATED_RECALL` is the
required authoritative predecessor. Delivery timing and the old shared retry
backlog exposed both an existing 200 and later 502 retries. The executor now
requires rev08 to exist in `INVALIDATED_RECALL`, while the next-day idempotency
key is stable over tenant, operating date, plan, and rev01. Both isolated jobs
were delivered twice and retained one draft receipt.

The isolated audit topic and push subscription were necessary because the
pre-existing shared subscription contains incompatible historical messages.
No backlog was deleted or sought past, and shared canonical rows were not
rewritten. The four reproducible audit Scheduler jobs are paused outside an
explicit qualification run.

## Frozen implementation candidate

- Implementation commit: `e2e700162284a21c42c51cece390c64d73cbaca4`.
- Orchestrator build: `3b5a5beb-241d-47f6-bbae-062ad4fb4ddb`, `SUCCESS`,
  `_GIT_SHA=e2e700162284a21c42c51cece390c64d73cbaca4`.
- Ledger build: `7582d5ed-cc7e-445e-9366-a0e3ac7066a7`, `SUCCESS`, same
  `_GIT_SHA`.
- Orchestrator revision: `full-shelf-orchestrator-00044-dp6`, 100% traffic,
  digest `sha256:bd7f8cfd870e8a3b44d64a71480f6fae0e9a2a6a806454839f9f561d471e2214`.
- Ledger revision: `full-shelf-plan-ledger-00023-q28`, 100% traffic, digest
  `sha256:6f78e6670995a177ca2692cb74d43e1711cdb0869ad88a65f3fa4ecb310501a2`.
- Orchestrator identity:
  `full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com`.
- Ledger identity:
  `full-shelf-ledger-sa@preflight-hackathon.iam.gserviceaccount.com`.
- Orchestrator project roles observed: `aiplatform.user`,
  `cloudtasks.enqueuer`, `cloudtrace.agent`, `modelarmor.user`,
  `pubsub.publisher`, and `spanner.databaseReader`. No Model Armor
  administrator or Spanner writer role was present.
- Private ledger invoker policy contained only the orchestrator service
  account. There was no direct operator or public invoker binding.

## Canonical preservation

Direct `full-shelf-main` reconciliation before this qualification and after all
managed calls and the complete suite was identical:

| Authority | Before | After |
| --- | ---: | ---: |
| canonical receipts | 17 | 17 |
| canonical approvals | 0 | 0 |

No canonical approval was fabricated. Both qualification universes are in
`full-shelf-audit-wp6-20260813` and are selected only by the deployed
allowlisted authority resolver.

## Canonical-shaped isolated result

Tenant: `audit-canonical-20260814`.

- Daily receipt `RCT-72D846D0DAD1DB7E115CFA37`, managed trace
  `d157cf9b4ef42fa1cef6ae45a5bb49c6`.
- Real GIS approval trace `1175b8a88ce7891aaeeb100becbd396d`;
  approval `RCT-B99BAD1D448035D944C7732A` persisted before activation
  `RCT-B06F9515E0517997A9439D59`.
- Approval bound rev07 to rev08, complete plan-diff hash
  `319ef8904bc6d4aa2cc1006ba3655baac4f75ff40e6f7b8469cfc397109f8c4b`,
  and KMS key version 1 of `approval-signer`.
- Waiting coordinator receipt `RCT-DC165AF3D44B55A668CB98D6`.
- Recall Pub/Sub message `21010486686372031`; managed hero trace
  `7378901a0d5b9f9bd73701c47baed7c2`; Cloud Run push returned 200 on
  `00044-dp6`.
- Managed Graph: 96 unique cases, 88 confirmed, eight unconfirmed, six
  physical nodes, maximum depth two, and no intermediate subtotal re-addition.
- Active movement barrier for `LTC-4471`; rev08 became
  `INVALIDATED_RECALL`.
- Recovery allocations: 18 cases to Agency 01 and 22 to Agency 02. Agency 04
  and Agency 05 remained safely supplied by their original `LTC-5090` orders,
  giving four safely supplied sites. Agency 03 retained an open 20-case
  shortfall.
- False containment receipt `RCT-D4FD29D8ADDE644A62E9C285` was `DENIED`
  with zero mutations. The terminal incident remained
  `PARTIALLY_CONTAINED`.
- Managed task
  `projects/preflight-hackathon/locations/us-central1/queues/full-shelf-deadlines/tasks/ack-7378901a0d5b9f9bd73701c47baed7c2`
  delivered with `Google-Cloud-Tasks`, HTTP 200, and committed
  `RCT-3AC859864CCA62096FE8B367` on the same trace.
- Next-day `PLAN-2026-08-15/rev01` is `DRAFT_WITH_CONSTRAINTS`; receipt
  `RCT-0D1AE1A2014B31A5934DFB70`, trace
  `34a22ffefa520837d6b25436a75b5a9d`. Duplicate delivery retained one row.
- The approval receipt arrived on an already-open SSE stream with cursor
  `r1.WyIyMDI2LTA4LTE0VDA1OjQ4OjU2LjE5MTE0NSswMDowMCIsIlJDVC03MkQ4NDZEMERBRDFEQjdFMTE1Q0ZBMzciXQ`.
  Reconnect after the latest cursor observed a heartbeat and zero duplicates.

## Altered isolated result

Tenant: `audit-altered-20260814`.

- Daily receipt `RCT-05415566F4B651B673B95D7A`, managed trace
  `094b9e82306169e81a8aa0a0fecbb445`.
- Real GIS approval trace `986b4e305856a5851529c92c5de3d784`;
  approval `RCT-6515CEADC14F0499BF40008C` preceded activation
  `RCT-C727AC75340C05A5D2C1555A`.
- Altered plan-diff hash
  `0b0bb1ae62f91267d4c068fe5a1a9d870f523b3d138ac982cfb0f66f43007a66`.
- Waiting receipt `RCT-AD177D0326E87FD656BE7015`.
- Recall Pub/Sub message `21007358010273230`; managed hero trace
  `41a4c932c4b0c7e7fac3e09d4e30b464`.
- Managed Graph: lot `ALT-8842`, 51 unique cases, 46 confirmed, five
  unconfirmed, eight nodes, maximum depth four.
- The same policy allocated nine cases to Agency 77 and fourteen to Agency 88,
  derived open shortfalls of three for Agency 88 and eight for Agency 99,
  blocked the altered lot, invalidated rev08, denied false containment with
  zero mutations, and persisted `PARTIALLY_CONTAINED`.
- Managed task
  `projects/preflight-hackathon/locations/us-central1/queues/full-shelf-deadlines/tasks/ack-41a4c932c4b0c7e7fac3e09d4e30b464`
  delivered with OIDC and committed `RCT-B9FCF7535817D4CE68330C64`.
- Next-day `PLAN-2026-08-15/rev01` is `DRAFT_WITH_CONSTRAINTS`; receipt
  `RCT-96DEDF35DE2372A1C9EF5B07`, trace
  `7e8f7607ca18dbd62c8f876d68012b31`. Duplicate delivery retained one row.
- The post-connect SSE event was `RCT-6515CEADC14F0499BF40008C`; reconnect
  after the latest cursor observed a heartbeat and zero duplicates.

## Model Armor durability evidence

The managed template uses Filter v3 selected by
`FILTER_VERSION_ALIAS_LATEST`. Deployed controls produced:

| Control | Trace | Managed verdict | ADK/Gemini spans | Receipt delta |
| --- | --- | --- | ---: | ---: |
| benign | `b298b161485b160e7bbf800dba7b7c21` | `NO_MATCH_FOUND` | `invoke_agent`, `call_llm`, `generate_content gemini-3.5-flash` | 0 |
| injection | `3ebc58725975e8d70c4e4487d2cac77b` | `MATCH_FOUND` | 0 | 0 |
| malicious URI | `bff4d4feb00c5b51804af22d6bf9d520` | `MATCH_FOUND` | 0 | 0 |
| dangerous content | `77cff58c528782f2c484cd7bc54836f2` | `MATCH_FOUND` | 0 | 0 |

The isolated receipt count was 14 before and after these four controls. Cloud
Trace contained eight spans for benign input and exactly one orchestrator span
for each rejection. Adapter-boundary tests separately cover HTTP 403, timeout,
malformed or partial response, failed filters, skipped filters, and unsupported
filter metadata. Those simulated conditions are not characterized as managed
service failures.

## Human checkpoint for independent re-audit

The authorized JavaScript origin must contain exactly
`http://localhost:8787`. Run the command below, open the printed localhost URL,
and select the allowlisted `markbrazinski@gmail.com` account. The helper
verifies the Google ID token locally, holds it only in memory while calling the
deployed route once, and never prints or writes it.

```bash
.venv/bin/python scripts/bootstrap_wp3_operator.py \
  --client-id=620464070103-ablut31si4neq0r8ibdc7hhtla1klls2.apps.googleusercontent.com \
  --approval-fixture=canonical --port=8787
```

Use `--approval-fixture=altered` for the second isolated universe. An auditor
must provision fresh allowlisted tenant IDs or operating-day scope before
repeating mutation-bearing runs; the frozen evidence tenants are intentionally
idempotent and are not resettable.

## Independent reproduction commands

```bash
# Complete safe suite
.venv/bin/python scripts/run_tests.py

# Create/update the four paused isolated jobs
.venv/bin/python scripts/configure_delta_audit_scheduler.py --fixture=canonical
.venv/bin/python scripts/configure_delta_audit_scheduler.py --fixture=altered

# Connect before approval; run once for each fresh isolated tenant
.venv/bin/python scripts/watch_delta_sse.py --tenant=audit-canonical-20260814

# After the real approval, execute only deployed entry points and poll authority
.venv/bin/python scripts/qualify_delta_hero.py --fixture=canonical
.venv/bin/python scripts/qualify_delta_hero.py --fixture=altered

# Read the managed Graph through the deployed orchestrator
.venv/bin/python scripts/verify_delta_graph.py

# Managed Model Armor allow/block controls and zero receipt delta
.venv/bin/python scripts/verify_deployed_model_armor.py \
  --tenant=audit-canonical-20260814

# Exact Cloud Trace span readback; use IDs printed by the previous command
.venv/bin/python scripts/verify_delta_traces.py \
  --benign=<BENIGN_TRACE> --rejected=<INJECTION_TRACE> \
  --rejected=<URI_TRACE> --rejected=<DANGEROUS_TRACE>

# Cursor reconnect: one server heartbeat and no duplicate projection
.venv/bin/python scripts/watch_delta_sse.py \
  --tenant=audit-canonical-20260814 --expect-no-event --heartbeat-count=1

# Canonical preservation
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12 gcloud spanner databases execute-sql \
  full-shelf-main --instance=fef-smoke-spanner --project=preflight-hackathon \
  --sql="SELECT (SELECT COUNT(*) FROM Receipts WHERE tenant_id='east-bay-food-bank') AS receipts, (SELECT COUNT(*) FROM Approvals WHERE tenant_id='east-bay-food-bank') AS approvals"
```

For managed Scheduler proof, resume, run twice, and pause the matching
`full-shelf-delta-{canonical,altered}-{daily,next-day}` job. Verify the Cloud
Run request log has user agent `APIs-Google`, HTTP 200, and revision
`full-shelf-orchestrator-00044-dp6`; then query exactly one receipt with the
operation's stable idempotency key. Direct callback invocation is not accepted
as managed proof.

## Known limitations

- The pre-existing shared production subscription retains historical retrying
  messages created under the rejected payload contract. The isolated audit
  topic/subscription prevents those messages from contaminating qualification.
  No destructive seek, purge, or canonical replay was performed.
- OpenTelemetry's Cloud Trace exporter and FastAPI `on_event` APIs emit
  deprecation warnings. They did not affect managed execution.
- Managed preview Agent Registry, Identity, Gateway, Runtime/Sessions, and
  Memory Bank remain unavailable and continue to be represented only by the
  previously approved seams.
- This is builder testimony. Every managed claim must be independently
  reproduced by the delta auditor.

REPAIR HANDOFF COMPLETE — INDEPENDENT DELTA AUDIT REQUIRED
