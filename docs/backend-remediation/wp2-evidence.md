# Work Package 2 — deterministic mutation boundary evidence

Recorded: 2026-08-13  
Gate: every authoritative write crosses one authenticated, tenant-scoped,
validated, deterministic, idempotent ledger executor and produces a committed
receipt; the orchestrator remains read-only.

This is builder evidence, not independent certification.

## Structural evidence

Classification: `STRUCTURALLY_VERIFIED`

- `full-shelf-orchestrator` and the `full-shelf-plan-ledger` entrypoint contain
  no Spanner transaction or mutation method calls.
- The only mutation implementation under the two service source trees and
  shared domain package is `SpannerLedgerCommandExecutor`.
- The command contract requires command/idempotency IDs, authenticated caller
  context, configured tenant, incident, logical role, expected revision, trace
  ID, strict typed payload, and a transactionally inserted receipt.
- Tenant scope is checked against `ALLOWED_TENANT_IDS` before a transaction is
  opened. Logical roles are checked per command. Unexpected denials stop
  orchestrator processing.
- Legacy mutation URLs remain authenticated but return HTTP 410. The approval
  compatibility route delegates to the same executor.
- Startup seeding and the direct-write probe were removed. The shared Spanner
  adapter is read-only.
- The schema migration is additive: receipt identity/idempotency columns and
  indexes plus movement barriers, recovery allocations, recovery shortfalls,
  and work items. No reset or destructive DDL exists.

## Local verification

Classification: `MEASURED`

- Canonical safe unit command: 55 tests passed.
- Supplemental mocked domain/orchestrator suite: 14 tests passed.
- Safe collection: 87 tests collected without execution.
- Python compilation and `git diff --check` passed.
- Structural AST tests reject mutation calls anywhere except the ledger
  executor.
- Tests cover altered noncanonical data, strict unknown-field rejection,
  tenant rejection before a transaction, role denial, stale revision denial,
  stable duplicate receipts, incident-scope mismatch, exact lifecycle,
  unconfirmed-case containment refusal, fail-closed reads, and preservation of
  the coordinator's existing child incident.

The legacy `apps/plan-ledger/tests/test_ledger_api.py` was not executed because
it invokes unmanaged KMS fallback/shared canonical data paths. It is a repair
target, not evidence.

## Isolated managed Spanner replay

Classification: `OBSERVED_LIVE`

Database: `full-shelf-audit-wp2-20260813`  
Tenant: `wp2-audit-tenant-20260813-v3`

The verifier refuses `full-shelf-main` and any database name that does not
contain `audit`. The final fresh-tenant run observed:

```json
{"active_barrier_count":1,"database":"full-shelf-audit-wp2-20260813","duplicate_additional_mutations":0,"duplicate_receipt":"RCT-9714FF87638C37CDF41A55AB","first_receipt":"RCT-9714FF87638C37CDF41A55AB","receipt_count":6,"recovery_allocation_count":1,"recovery_shortfall_count":1,"refusal_status":"DENIED","replay_after_prior_commit":false,"stale_plan_mutations":0,"stale_status":"DENIED","tenant":"wp2-audit-tenant-20260813-v3","work_item_count":1}
```

This directly observed one coordinator mutation plus its stable duplicate,
stale-revision denial, recall incident creation, active lot barrier, root work
item, altered safe allocation, altered shortfall, and explicit refusal receipt.
Duplicate and stale commands reported zero additional operational mutations.

Two earlier verifier attempts are retained as `FAILED` verifier evidence:

1. The first committed the v2 altered-tenant commands but readback reused a
   single-use snapshot.
2. The corrected readback then assumed first-delivery mutation counts despite
   correctly receiving stable replay receipts.

After fixing only those verifier assumptions, both v2 replay recovery and the
fresh v3 current-code run passed. The Spanner client emitted a non-fatal Cloud
Monitoring metrics-export warning because local client resource labels omitted
`instance_id`; authoritative Spanner commits and readback succeeded.

## Canonical database preflight

Classification: `OBSERVED_LIVE`

Before any canonical DDL or WP2 replay, `full-shelf-main` contained:

| Tenants | Plan revisions | Incidents | Receipts |
|---:|---:|---:|---:|
| 1 | 3 | 2 | 3 |

Read-only DDL inspection confirmed the canonical database does not yet contain
the WP2 receipt columns/index or new barrier/recovery/work-item tables. No WP2
test has run against the canonical database.

## Remaining gate

Classification: `NOT_PROVEN`

- Canonical additive DDL has not yet been applied.
- WP2 images have not yet been built or deployed.
- Deployed command authentication, duplicate replay, refusal, and direct
  authoritative reconciliation remain to be observed before WP2 can be marked
  deployed or complete.
