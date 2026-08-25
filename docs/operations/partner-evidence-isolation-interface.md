# Partner-evidence isolation: required interface

**Status:** DESIGNED — not implemented. Deferred to the Golden Runtime Controller commission.
**Date:** 2026-08-25
**Applies to:** `apps/orchestrator/src/main.py:process_partner_evidence`

## The gap

`GOLDEN_DEMO_EVENT_CONTRACT` §6.2 requires the complete partner branch to reach
`96/96` inside an isolated authority while canonical Friday history remains
unchanged at `88/96`. §6 opens with the binding constraint: *"Neither branch
advances or rewrites the canonical cursor."*

**No isolation mechanism exists on this path today.** Verified against the live
code:

- `process_partner_evidence` (`main.py`) accepts no `branch`, `isolated`,
  `proof`, or `dry_run` parameter, and `PartnerEvidenceRequest` cannot express
  one.
- Tenant and database are derived solely from the caller's verified OIDC
  subject via `PARTNER_CALLBACK_AUTHORITY_JSON`. A request cannot select scope,
  which is correct for authentication and is *why* isolation cannot currently
  be requested.
- On `APPLIED`, `ledger_executor.py` mutates `CustodyNodes` and `WorkItems` in
  that same database and sets `domain_count = 2`.

Consequence: **a complete partner callback on this endpoint would move
canonical custody from 88/96 to 96/96.** The `96/96` view the demo shows today
is a replay-fixture lens (`tools/replay/fixtures/partner_complete.json`), not
an executed isolated write. That is a truthful fallback, and must be classified
`DESIGNED`, never `OBSERVED_LIVE`.

## What still holds

The invariant this commission was asked to preserve is intact and tested:

- No agent can mutate authoritative state. Partner Operations proposes; the
  deterministic verifier decides; only the private ledger commits.
  (`test_single_mutation_authority.py`, `test_no_authoritative_writes.py`)
- A vague callback yields `DENIED`, zero domain mutations, one evidence
  mutation — with the abstaining proposal persisted rather than rejected at the
  schema layer. (`test_partner_evidence.py`)

The gap is that an isolated *branch* cannot be selected, not that agents can
write.

## Required interface

The isolation primitive already exists and is enforced:
`AuthorityScopeResolver` (`packages/domain/full_shelf_domain/authority.py`)
maps tenant to database and raises `AUDIT_DATABASE_MUST_BE_ISOLATED` when an
audit scope is not physically separate. Its scope kinds are `CANONICAL`,
`CANONICAL_OPERATING_DAY`, `AUDIT_ISOLATED`, and
`AUDIT_ISOLATED_FRESH_OPERATING_DAY`.

What the Golden Runtime Controller must add:

1. **Config-derived scope selection.** The callback authority record — not the
   request body — names whether a given callback principal writes to a
   canonical or `AUDIT_ISOLATED` scope. `AGENTS.md` requires tenant identity to
   derive from verified authentication context; a body-supplied isolation flag
   would violate that and must not be added.

2. **Scope threaded to the ledger command.** `execute_ledger_command` receives
   the resolved scope so isolated writes land in the isolated database that
   `authority.py` already guarantees is separate.

3. **Canonical invariance proven by re-read, not asserted.** After an isolated
   `APPLIED`, the acceptance test must re-read canonical `CustodyNodes`,
   `Incidents`, `RecoveryShortfalls`, and `Receipts` and prove each unchanged.
   Asserting "canonical state stayed unchanged" without re-reading it proves
   nothing.

4. **Branch return.** Leaving the branch restores the canonical view at 88/96
   with the canonical cursor unmoved.

## Constraint on the implementation

`AGENTS.md` locks the architecture to exactly two Cloud Run services. If
isolation cannot be achieved without a third deployed service, that is a
product-owner change request, not an implementation decision. Escalate rather
than adding a service.

## Related deferred items

These share the Golden Runtime Controller commission and are likewise
submission-blocking for `FILMABLE_GOLDEN_PATH_ACCEPTED`:

| Requirement | Contract | Status |
|---|---|---|
| Isolated branch cannot move the canonical cursor | §8.10 | Absent — no cursor exists; `tools/replay/server.py` splices proof fixtures into the same linear timeline as canonical beats |
| Branch return restores 88/96 | §8.11 | Absent |
| Replay session isolation and reset | §8.1–8.3 | Absent — the replay server holds no per-session state |
| Gap-free ordinal event sequence per session | §8.14 | Absent — cursors are opaque, not ordinal |

Already satisfied, and not part of that commission: server-side future-state
exclusion (§8.9), altered-approval denial (§10.4), SSE never carrying raw
source text (§10.2), and — as of this commission — the event 9 to event 10
approval invariant.
