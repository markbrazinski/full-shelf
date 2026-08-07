# ADR 001: Deterministic Mutation Invariant & ADK Read-Only Boundary

## Context
In a safety-critical food-bank fulfillment control plane, probabilistic language models (Gemini via Google ADK) must assist in interpretation, route recovery planning, and natural language explanation. However, allowing an LLM or agent direct write access to operational state (Spanner) introduces risks of unintended mutations, hallucinated allocations, or stale state overrides.

## Decision
We enforce a strict physical and architectural boundary:
1. `apps/orchestrator` (ADK Agent Service) has **read-only** access to Spanner operational state.
2. All operational mutations (plan revision, lot barrier, order reroute, pickup conversion, receipt creation) must route through `apps/plan-ledger`.
3. `apps/plan-ledger` validates tenant isolation, plan revision preconditions, capacity limits, and cryptographic approvals before executing deterministic Spanner transactions.
4. Gemini agents propose actions; `plan-ledger` disposes and records immutable transactional receipts.

## Consequences
- Zero direct database writes from ADK agents.
- Full auditability via immutable receipts tied to correlated trace IDs.
- Deterministic policy enforcement guarantees physical safety laws (e.g. truck weight/case capacity limits) are never violated.
