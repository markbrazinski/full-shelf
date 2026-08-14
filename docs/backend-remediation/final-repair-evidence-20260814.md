# Final repair builder evidence — 2026-08-14

This is builder evidence, not acceptance. Independent audit remains required.
The repair was performed from the root authority record and latest delta-audit
attachment without relying on prior builder testimony. The original external
authority packet was not present in the checkout; the resolved WP0 authority
record remained the repository authority source.

## Runtime boundary

- `STRUCTURALLY_VERIFIED` — Runtime commits, in order, are `9e4f68b`,
  `dfaf7e4`, `b3a1c58`, and `4201d26`. Evidence is committed separately.
- `OBSERVED_LIVE` — `full-shelf-orchestrator-00049-wjv` serves 100% of traffic
  from immutable digest
  `sha256:8f8134b4feed5f0000aed1a29018fc1d8f1e5bb57e39b2f3ba68fc77bfacafae`.
- `OBSERVED_LIVE` — `full-shelf-plan-ledger-00024-9zc` serves 100% of traffic
  from immutable digest
  `sha256:1d3ff569a37ee979270e35f9a1552e38269bd5ebf173324429a4d4068c047a14`.
- `OBSERVED_LIVE` — The additive migration
  `006_final_authority_and_idempotency.sql` was applied to the main and isolated
  audit databases. No database was reset, reseeded, or backfilled.

## Remaining-failure disposition

1. `STRUCTURALLY_VERIFIED` — Receipt replay now compares a deterministic
   fingerprint of the complete command. Reusing an approval idempotency key
   with any changed signed-envelope field raises `IDEMPOTENCY_KEY_COLLISION`
   before mutation. Legacy approval receipts without a fingerprint are not
   accepted as safe replays.
2. `STRUCTURALLY_VERIFIED` — The approval contract, KMS canonical signing
   string, persistence, and activation checks bind `tenant_id`, `operating_day`,
   and `authority_scope`. The four live approvals below persist those bindings.
3. `OBSERVED_LIVE` — All four isolated Scheduler jobs are `ENABLED`. The same
   unchanged next-day job was run repeatedly; its pending-scope resolver selected
   one committed scope at a time without auditor payload/configuration changes.
4. `OBSERVED_LIVE` — Historical authenticated Pub/Sub events older than 24 hours
   were acknowledged as `STALE_PUBSUB_EVENT` with zero mutation. The final
   revision produced four observed push responses, all HTTP 200, after an earlier
   revision's retry storm had produced 502 responses.
5. `OBSERVED_LIVE` — Scheduler-created authority scopes were fresh and distinct:
   `audit-canonical-20260814-036ab83d29`,
   `audit-canonical-20260814-ca34674c69`,
   `audit-altered-20260814-b4d258c7b5`, and
   `audit-altered-20260814-6c7cdd8557`. No reset endpoint or canonical-state
   mutation was used.
6. `STRUCTURALLY_VERIFIED` — Projection and SSE routes derive their only
   tenant/day from deployment configuration after Google token verification;
   they expose no caller-selected tenant parameter. `OBSERVED_LIVE` — both
   routes rejected unauthenticated cross-tenant query attempts with HTTP 401.
7. `STRUCTURALLY_VERIFIED` — The static demo-beat array was removed. The route
   now reads committed plans, approvals, and incidents for the verified fixed
   authority and cannot synthesize approval history.
8. `MEASURED` — Each of the four scopes recorded three successful managed
   Cloud Tasks callback requests (the application-created delivery plus two
   separately named qualification deliveries sharing the event idempotency key),
   while authoritative Spanner contains exactly one
   `RECORD_ACKNOWLEDGMENT_HOLD` receipt and two mutations per scope. The
   qualification runner rejects any receipt-count increase.
9. `STRUCTURALLY_VERIFIED` — ADR 003 and the approval schemas specify only the
   rev07 to rev08 approval. Recall invalidates rev08 in place; no rev09 is
   created. `OBSERVED_LIVE` — all four scopes end with rev08
   `INVALIDATED_RECALL` and tomorrow's rev01 `DRAFT_WITH_CONSTRAINTS`.

## Fresh managed executions

`OBSERVED_LIVE` — Each scope has exactly one KMS-backed approval whose persisted
`authority_scope` is `<tenant>@2026-08-14`, one truthful food-safety incident at
`PARTIALLY_CONTAINED`, and one acknowledgment hold. Final plan state:

| Profile | Fresh scope | rev08 | Tomorrow rev01 |
| --- | --- | --- | --- |
| canonical 1 | `audit-canonical-20260814-036ab83d29` | `INVALIDATED_RECALL` | `DRAFT_WITH_CONSTRAINTS` |
| canonical 2 | `audit-canonical-20260814-ca34674c69` | `INVALIDATED_RECALL` | `DRAFT_WITH_CONSTRAINTS` |
| altered 1 | `audit-altered-20260814-b4d258c7b5` | `INVALIDATED_RECALL` | `DRAFT_WITH_CONSTRAINTS` |
| altered 2 | `audit-altered-20260814-6c7cdd8557` | `INVALIDATED_RECALL` | `DRAFT_WITH_CONSTRAINTS` |

Cloud Scheduler returned transient `UNAVAILABLE` on two manual attempts before
publish. Retrying the unchanged enabled jobs succeeded; the failed attempts
caused no application mutation. Final job status for both next-day jobs is
successful and all four jobs remain enabled for independent audit.

## Verification

- `MEASURED` — Broad repository suite: 166 passed, 21 warnings.
- `MEASURED` — Required safe suite plus locked-contract test: 78 passed,
  5 warnings.
- `MEASURED` — Focused managed-callback suite: 15 passed.
- `STRUCTURALLY_VERIFIED` — `git diff --check` succeeded before runtime commits.
- `NOT_PROVEN` — This builder has not independently certified the repair. A
  fresh auditor must replay identity, collision, projection/SSE, and managed
  delivery checks before acceptance.
