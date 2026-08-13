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

## Canonical database migration and reconciliation

Classification: `OBSERVED_LIVE`

Before canonical DDL, `full-shelf-main` contained:

| Tenants | Plan revisions | Incidents | Receipts |
|---:|---:|---:|---:|
| 1 | 3 | 2 | 3 |

Read-only DDL inspection confirmed the WP2 objects were absent. The exact
additive migration `infra/spanner/migrations/001_wp2_deterministic_boundary.sql`
was then applied. Readback observed the new receipt columns/index and the
`MovementBarriers`, `RecoveryAllocations`, `RecoveryShortfalls`, and `WorkItems`
tables.

Canonical counts immediately after migration, and again after the deployed
tenant-denial request, were unchanged:

| Tenants | Plan revisions | Incidents | Receipts | Barriers | Allocations | Shortfalls | Work items |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3 | 2 | 3 | 0 | 0 | 0 | 0 |

No WP2 successful mutation or replay was run against the canonical tenant.

## Build and deployment

Classification: `OBSERVED_LIVE`

Both builds came from full Git SHA
`22d86f9fb5710524343f1b853aa210a012aec478` and succeeded:

| Service | Cloud Build | Image digest | Ready revision |
|---|---|---|---|
| orchestrator | `3831c3d6-ec10-4798-9923-ccff13f41a22` | `sha256:90b542c9e0e6db5336f0fd32609e7574f1f21058bfe9c061046e046761861066` | `full-shelf-orchestrator-00024-kwm` |
| plan-ledger | `e6b1be62-4c83-4283-98d0-385667b5ab9a` | `sha256:9389776af3d7f51d34514d63865216f59f6ef58eca0574b7a2f00f21b830f7f4` | `full-shelf-plan-ledger-00017-7mh` |

Cloud Run reported both revisions ready and the orchestrator revision serving
100 percent of traffic. Runtime identities remained separated:

- orchestrator: `full-shelf-orchestrator-sa`, with
  `roles/spanner.databaseReader` and no database writer role;
- plan-ledger: `full-shelf-ledger-sa`, with
  `roles/spanner.databaseUser`;
- private ledger invoker policy contains the orchestrator service account and
  the operator only, with no `allUsers` member.

The ledger deployment has `ALLOWED_TENANT_IDS=east-bay-food-bank`.

## Deployed denial and zero-mutation reconciliation

Classification: `OBSERVED_LIVE`

An identity token was minted by impersonating the configured orchestrator
service account, with the exact ledger audience and service-account email
claim. A valid `PERSIST_COORDINATOR` command using an unauthorized tenant then
reached the deployed generic command route and returned:

```json
{"detail":"TENANT_SCOPE_NOT_AUTHORIZED"}
```

HTTP status was 403. Direct authoritative count reconciliation before and after
the request was identical, including three receipts and zero WP2 operational
rows. Anonymous access to the ledger returned the Cloud Run platform's 403.

The successful duplicate replay was deliberately performed against the
isolated managed audit database rather than the canonical tenant. The deployed
image is the same Git-bound executor image verified there; this is not a claim
that a successful canonical deployed mutation was exercised.

## Package result

Classification: `OBSERVED_LIVE`

All WP2 acceptance outcomes are observed through structural checks, direct IAM
inspection, isolated managed mutation replay, deployed tenant denial, and
authoritative reconciliation. The mutation boundary is not bypassable through
the inspected service code or deployed IAM roles. WP3 may begin. This is a
builder package result, not final backend acceptance.

## Limitations carried forward

Classification: `NOT_PROVEN`

- A successful command and its duplicate were not sent through the deployed
  service against the canonical tenant, because remediation tests may not
  mutate shared canonical data.
- Both published orchestrator `run.app` URLs returned a Google platform 404
  during an unauthenticated health probe even though Cloud Run reported the
  revision ready, ingress `all`, public invoker IAM, and 100 percent traffic.
  This routing anomaly must be resolved before a later deployed end-to-end
  replay; it does not weaken the separately exercised private ledger boundary.
