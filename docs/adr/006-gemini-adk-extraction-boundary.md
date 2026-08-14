# ADR 006: Gemini 3.5 structured extraction through Google ADK

## Context

Recall extraction is advisory interpretation of untrusted text. The prior code
declared `gemini-3.5-flash` in evidence but configured the load-bearing ADK
Agent with `gemini-2.5-flash`, used an unbounded text response, and allowed the
hero loop to continue after a returned failure object. Session and run
identifiers were not both preserved.

Managed ADK Runtime/Sessions remain unavailable and must not be implied. The
orchestrator remains read-only and only the deterministic ledger may mutate
authoritative state.

## Decision

1. `GEMINI_MODEL_ID` defaults to the locked `gemini-3.5-flash`; startup and
   invocation refuse identifiers below Gemini 3.5.
2. The load-bearing Google ADK `Agent` itself receives that identifier. The
   invocation occurs only through an ADK `Runner`; there is no direct Gen AI
   extraction fallback.
3. The Agent uses a strict Pydantic output schema with exactly five fields:
   lot ID, product name, hazard, required action, and source anchor.
   An ADK `BuiltInPlanner` disables model thinking for this bounded extraction
   task so the output budget is reserved for the structured response. Any
   non-`STOP` final response is incomplete and requires manual review.
4. The orchestrator independently validates the final ADK response against the
   same schema and verifies every extracted value occurs in the screened source
   notice. A purported lot ID must additionally occur in explicit `lot`,
   `lot id`, or `lot number` context so a bulletin/document identifier cannot
   be silently reclassified as a lot. Missing, extra, malformed, ambiguous, or
   fabricated values require manual review.
5. The actual ADK-created session ID, Runner invocation ID, final event ID,
   configured model, framework version, and application correlation ID are
   returned and persisted as a sanitized structured Cloud Logging record.
6. `InMemorySessionService` is truthfully named as the session backend. It is
   not represented as managed ADK Sessions or authoritative state. Durable day
   coordinator state remains in Spanner.
7. Model, ADK, output-schema, source-anchor, or identifier failure sets
   `downstream_allowed=false`; the hero loop stops before graph work or ledger
   invocation. No canonical extraction fallback exists.
8. The judge-protected extraction preflight stops at deterministic policy
   review and never invokes the ledger. In the full hero loop, the same
   application correlation ID propagates into later ledger commands and
   receipts only after successful extraction.

## Consequences

- ADK is load-bearing and supplies the real session, run, and event IDs.
- Model output remains advisory and cannot mutate Spanner.
- Invalid or unavailable model output becomes a visible manual-review state.
- Cloud Logging persists sanitized invocation evidence; raw notice text and raw
  model output are excluded from that record.
- A deployed invocation and managed log readback are still required before an
  `OBSERVED_LIVE` claim.
