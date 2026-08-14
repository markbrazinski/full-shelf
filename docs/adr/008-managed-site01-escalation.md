# ADR 008: Durable Site 01 escalation through Cloud Tasks

## Context

The prior producer returned a local fallback on `CreateTask` failure, omitted
an explicit OIDC audience, and the callback treated task headers as
authentication. A forged direct callback could therefore reach ledger logic.

## Decision

1. A deployed application decision reads the open recall and Site 01 hold, then
   calls managed `CreateTask`. Failure is surfaced; no local success exists.
2. The task records its immutable managed name, queue, target URL, explicit
   audience, and delivery service account.
3. The callback first verifies the Google ID token at the same strict boundary
   as Pub/Sub. Task/queue headers are delivery context only, never identity.
4. The task name must match the decision ID in the managed payload. Tenant,
   incident, and site scope are fixed to the authorized escalation.
5. The callback can mutate only by sending
   `RECORD_ACKNOWLEDGMENT_HOLD` to the authenticated plan-ledger. The ledger
   atomically records the accepted inbound task event, truthful hold details,
   delivery identity/audience, and receipt.
6. The stable task decision ID is the ledger idempotency key. Managed
   redelivery returns the original receipt with zero additional mutations.

## Consequences

A manually invoked callback cannot pass. Cloud Tasks creation and delivery must
both be observed live before this path receives an `OBSERVED_LIVE` label.
