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
2. A Pub/Sub planning envelope must contain managed message ID and publish time.
   The source operating day is the verified publish time converted to
   `America/Los_Angeles`; the next operating date is that day plus one. Next-day
   product identity is tenant, source operating day, `PLAN_NEXT_DAY_REQUESTED`,
   next-day plan ID, and revision. Message ID, raw publish time, trace/request
   ID, delivery attempt, and qualification profile are transport context only.
3. The orchestrator reads, but does not write, the current recall, movement
   barrier, recovery shortfall, acknowledgment hold, confirmed-safe inventory,
   and operational fleet state. Missing required truth fails closed.
4. One authenticated `CREATE_NEXT_DAY_DRAFT` ledger command atomically persists
   the accepted inbound event, `rev01` draft, three inherited constraints, the
   next operating day's coordinator, and a receipt. The new coordinator has no
   transferred child incidents and remains `HUMAN_APPROVAL_REQUIRED`.
5. Idempotency is keyed by the stable next-day product identity, so duplicate
   delivery returns the original receipt and creates no duplicate draft.
6. Authentication precedes disposition. Authenticated stale and permanent
   schema/business rejections return 2xx with explicit zero-mutation
   dispositions; authentication failures remain 401/403 and transient managed
   or persistence failures remain retryable 5xx. Disposition logs correlate the
   managed message ID, event type, trusted age, request trace, and receipt when
   available.

## Consequences

Scheduler publication alone is not evidence of continuity. Proof requires the
authenticated deployed callback plus direct readback of the event, constraint,
coordinator, draft, and receipt rows. Existing inconsistent authoritative
state is never silently filled from canonical constants.
