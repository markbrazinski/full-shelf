# Resolved authority record

This document records the authority decisions that remain canonical for the
implementation. It deliberately contains no deployment status, revision,
receipt, or builder-acceptance claims.

## Event and product authority

- Official event: Google All Things Agentic Hackathon, Fortified Enterprise
  Fleet track.
- Full Shelf Build Book v1.1 controls the product scenario.
- Current recall custody is `24 + 22 + 20 + 10 + 8 + 12 = 96` physical cases.
  Agency 01's historical 18-case receipt is not a current-position subtotal,
  and Site 01's eight cases are downstream of Agency 01.
- Truck 2 has capacity 60 and current load 36. It absorbs O202's 22 cases only;
  O203's 20 cases become refrigerated partner pickup.
- Recovery replaces 40 safe cases: 18 for Agency 01 and 22 for Agency 02.
  Agency 03 retains a truthful 20-case shortfall and Site 01 remains
  unconfirmed.

## Approval and lifecycle authority

- The approval binds the complete `rev07` to `rev08` diff, both order actions
  and quantities, plan and truck-incident IDs, verified human principal,
  expiry, diff SHA-256, and KMS key version.
- Recall invalidates `rev08` in place. It does not create another revision.
- The only recall lifecycle is `DETECTED → SCOPING →
  CONTAINMENT_IN_PROGRESS → PARTIALLY_CONTAINED → CONTAINED → CLOSED`.
- The canonical scenario ends at unresolved `PARTIALLY_CONTAINED`.
- Tomorrow's `rev01` is `DRAFT_WITH_CONSTRAINTS — HUMAN APPROVAL REQUIRED` and
  inherits the movement barrier, shortfall priority, and acknowledgment hold.

## Managed-service and identity authority

- Model Armor must perform an actual supported managed sanitization operation
  before Gemini and fail closed on service, response, filter, or version error.
- Gemini 3.5 Flash or newer executes through Google ADK. Model or structured
  output failure stops downstream processing.
- Human approval uses a Google-signed operator ID token verified by immutable
  subject. Workload and human identities remain separate.
- Pub/Sub and Cloud Tasks callbacks verify Google-signed workload OIDC with an
  exact audience and expected immutable service-account identity.
- Spanner Graph uses parameterized multi-hop GQL over authoritative Spanner
  state. SSE tails only committed authoritative events in durable order.

## Mutation and topology authority

- Exactly two Cloud Run services exist: `full-shelf-orchestrator` and
  `full-shelf-plan-ledger`.
- Spanner is authoritative. The orchestrator, ADK agents, and model reasoning
  are read-only and advisory.
- Every authoritative write crosses the private deterministic plan ledger with
  authenticated workload identity, tenant and incident scope, expected
  revision, deterministic policy, idempotency key, transactional receipt, and
  actual trace correlation.
- A denied command or failed precondition applies zero authoritative mutations.
- No memory, cache, session, browser, model context, or separate graph store may
  own authoritative operational state.

The root `AGENTS.md`, contracts under `packages/contracts`, Spanner schema under
`infra/spanner`, and accepted ADRs under `docs/adr` provide the tracked
implementation constraints. External audit evidence may substantiate runtime
claims but does not override this authority record.
