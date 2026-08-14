# ADR 007: Authenticated managed planning continuity

## Context

The Scheduler jobs publish to Pub/Sub, but the push subscription did not bind
an explicit OIDC audience and the public callback did not verify the token.
The callback also invoked judge-protected route functions, used hardcoded
dates, and returned hardcoded constraints that were not persisted with the
draft.

## Decision

1. Pub/Sub and Cloud Tasks use one explicit orchestrator service audience and
   one allowlisted delivery service-account subject/email. Dedicated callback
   routes verify signature, issuer, expiration, exact audience, subject, and
   email before interpreting request data.
2. A Pub/Sub planning envelope must contain the managed message ID and publish
   time. The next operating date is the publish date in
   `America/Los_Angeles` plus one day.
3. The orchestrator reads, but does not write, the current recall, movement
   barrier, recovery shortfall, acknowledgment hold, confirmed-safe inventory,
   and operational fleet state. Missing required truth fails closed.
4. One authenticated `CREATE_NEXT_DAY_DRAFT` ledger command atomically persists
   the accepted inbound event, `rev01` draft, three inherited constraints, the
   next operating day's coordinator, and a receipt. The new coordinator has no
   transferred child incidents and remains `HUMAN_APPROVAL_REQUIRED`.
5. Idempotency is keyed by tenant and calculated operating date, so duplicate
   delivery returns the original receipt and creates no duplicate draft.

## Consequences

Scheduler publication alone is not evidence of continuity. Proof requires the
authenticated deployed callback plus direct readback of the event, constraint,
coordinator, draft, and receipt rows. Existing inconsistent authoritative
state is never silently filled from canonical constants.
