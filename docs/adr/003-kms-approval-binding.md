# ADR 003: Persisted, Complete KMS Approval Binding

## Status

Accepted for Build Book v1.1.

## Context

The `rev07` to `rev08` repair is one human decision containing two inseparable
changes: reroute Order O202 to Truck 2 for 22 cases and convert Order O203 to
refrigerated partner pickup for 20 cases. Activation without an authoritative
approval row, or authorization of only one action, is invalid.

## Decision

1. The plan ledger verifies a real Google human ID token against the configured
   OAuth audience and operator allowlist. Workload OIDC remains independently
   required for the orchestrator caller.
2. The complete canonical envelope binds approval ID, tenant ID, operating day,
   the derived `tenant_id@operating_day` authority scope, human principal, truck
   incident ID, plan ID, source revision `rev07`, proposed revision `rev08`, both
   order actions and quantities, the canonical plan-diff SHA-256, expiration,
   and exact KMS key version.
3. Cloud KMS signs the SHA-256 digest of that complete envelope. The ledger
   verifies the managed signature before persisting the approval.
4. `PERSIST_REPAIR_APPROVAL` commits the approval and its complete canonical
   plan diff in one transaction and returns its own receipt.
5. `ACTIVATE_APPROVED_REPAIR_PLAN` runs in a later transaction. It reads the
   persisted approval, re-computes the plan-diff hash, re-verifies the managed
   signature and expiration, validates revision and vehicle-capacity
   preconditions, and derives the mutations from the persisted diff.
6. Changed tenant, operating day, authority scope, identity, incident, plan,
   revision, action, order, quantity, target, hash, expiration, or key version
   fails closed with zero activation mutations. Idempotent replay returns the
   original stable receipt only when the stored request fingerprint matches.

The retired `/api/v1/actions/execute` one-step route returns HTTP 410 and cannot
perform a mutation.

## Consequences

- Approval authority is independently queryable before activation.
- Approval and activation have separate transactional receipts.
- A valid KMS signature alone is insufficient without the matching persisted
  approval, authoritative revision, and feasible capacity.
- The UI must not claim activation from an unpersisted or partially bound
  approval.
