# Full Shelf implementation constitution

Read this file completely before acting anywhere in this repository. It is the
canonical, tool-neutral implementation contract for Codex, Claude Code,
Antigravity, Gemini, and future builders. Nested instruction files may add
directory-specific detail, but may not weaken this file.

## Project identity

Full Shelf is a standing food-bank fulfillment control plane for a food-bank
operations director. It is not recall-only software, a route planner, a WMS or
TMS replacement, agent chat, a generic agent platform, or an infrastructure
dashboard. Preserve its ordinary-disruption repair, later safety revision, and
governed next-day continuity thesis.

## Authority order

Apply authority in this order:

1. Published hackathon rules and judging criteria.
2. Full Shelf Build Book v1.1.
3. Latest independent audit.
4. Strategy handoff.
5. Repository contracts, schemas, and this `AGENTS.md`.
6. Approved implementation commission.
7. Builder reports, which are non-authoritative testimony.

The supplied authority packet is resolved in
[the resolved authority record](docs/authority/resolved-baseline.md). Repository
contracts live under [`packages/contracts`](packages/contracts), the current
schema is [`infra/spanner/schema.sql`](infra/spanner/schema.sql), and accepted
architectural decisions live under [`docs/adr`](docs/adr). An older ADR or
implementation does not override a higher authority. Escalate contradictions;
never resolve them silently.

## Locked architecture

- There are exactly two AUTHORITATIVE Cloud Run services:
  `full-shelf-orchestrator` and `full-shelf-plan-ledger`. A further
  authoritative service requires a formal change request.
- AMENDMENT CR-001 (approved 2026-08-30). A third, non-authoritative service,
  `full-shelf-judge`, serves the authenticated judge experience. Its scope is
  closed: serve the judge frontend, integrate Cloud Identity Platform, verify
  the judge's Identity Platform token, own the judge session/lease, call the
  private orchestrator with its own service identity, and emit the structured
  login event. It may NOT contain agent logic, mutate Spanner directly, call
  the plan ledger directly, weaken authentication on either authoritative
  service, or become another source of operational truth. It is not evidence
  of managed-path behavior, and judge activity is confined to the isolated
  `full-shelf-judge` database — never canonical `full-shelf-main`.
- Spanner is authoritative. Spanner Graph traverses the same authoritative
  Spanner state; it is not a second store.
- The orchestrator, ADK agents, and model reasoning are read-only and advisory.
- Only the deterministic plan ledger may mutate authoritative state. Direct
  orchestrator Spanner writes are prohibited.
- Memory, session, cache, browser, and model context systems may not own
  authoritative operational state.

## Authoritative mutation contract

Every authoritative mutation requires all of the following:

- authenticated workload identity;
- authenticated acting principal when human authority is required;
- tenant and incident scope;
- expected plan revision;
- structured validation and a deterministic policy decision;
- idempotency key;
- transactional mutation receipt;
- correlated trace ID from the actual execution; and
- zero mutations on denial or failed precondition.

All writes, including callback-driven writes, must cross the private ledger.
Gemini and the orchestrator may propose a command but may not apply it.
The `rev08` approval binds `rev07`, the complete proposed diff, both O202 and
O203 actions and quantities, approver principal, plan and incident IDs,
expiration, plan-diff SHA-256, and KMS key version. Altering any bound value
invalidates approval and causes zero mutations.

## Authentication requirements

- Cryptographically verify Google-signed tokens: signature, allowed issuer,
  expiration, exact audience, and allowed immutable subject.
- Never treat decoded claims, trusted headers, API keys, email strings, or
  caller-supplied identities as authentication.
- Derive tenant identity from verified authentication context, never from a
  request-body override.
- The plan ledger must not grant `allUsers` and must independently authenticate
  every caller before route logic.
- Pub/Sub and Cloud Tasks callbacks must verify the expected Google
  service-account identity and exact callback audience.
- Human approval requires a real Google-signed operator identity. Workload and
  human identities are separate.
- Before KMS signing or activation, the ledger must independently verify the
  original human token and the complete approval binding.

## Canonical scenario invariants

- Morning plan provenance is `GENERATED 05:30 · APPROVED 06:45 · ACTIVE rev07`.
- Plan transition: `rev07 → rev08`.
- Recalled lot: `LTC-4471`; safe replacement lot: `LTC-5090`; hazard:
  E. coli O157:H7.
- Truck 2, capacity 60 with existing load 36, absorbs only O202's 22 cases.
- O203's 20 cases become refrigerated partner pickup; `36 + 22 + 20 = 78`
  proves both orders cannot fit.
- Current-position custody is `24 + 22 + 20 + 10 + 8 + 12 = 96` physical
  cases. O201's 18 cases are an intermediate historical subtotal and must not
  be re-added. Site 01's eight cases are downstream of Agency 01 and must not
  be double-counted.
- Recovery replaces 40 safe cases: 18 for Agency 01 and 22 for Agency 02.
- Agency 03 retains a truthful 20-case shortfall.
- Site 01's eight cases remain unconfirmed.
- The incident reaches `PARTIALLY_CONTAINED`, never a fabricated completion.
- Tomorrow's `rev01` status is
  `DRAFT_WITH_CONSTRAINTS — HUMAN APPROVAL REQUIRED`; it inherits the lot
  barrier, shortfall priority, and acknowledgment hold.

Do not change scenario quantities, identifiers, provenance, or terminal truth
for implementation convenience.

## Incident lifecycle

The only lifecycle is:

`DETECTED → SCOPING → CONTAINMENT_IN_PROGRESS → PARTIALLY_CONTAINED → CONTAINED → CLOSED`

Creation does not jump to a terminal state. `PARTIALLY_CONTAINED` is unresolved,
not contained, resolved, or closed.
It may be entered only after all 96 physical cases are traced, known unsafe
movements are blocked, 40 safe replacements are allocated, 88 cases are
confirmed, Site 01's eight cases remain explicitly unconfirmed, and false
containment is refused.

## Model and managed-service requirements

- Gemini 3.5 Flash (`gemini-3.5-flash`) or newer executes through Google ADK.
  Persist the truthful model identifier and ADK session and run identifiers.
- Model invocation failure, invalid structured output, or schema failure stops
  downstream processing.
- Model Armor performs genuine managed sanitization before Gemini and fails
  closed.
- Scheduler, Pub/Sub, and Cloud Tasks claims require actual managed delivery.
- Spanner Graph claims require parameterized multi-hop GQL over authoritative
  data.
- SSE originates only from committed authoritative events, resumes in order,
  and remains open for new events.
- Trace, receipt, invocation, delivery, and evidence identifiers come from the
  actual execution they describe.

Managed preview Agent Registry, Agent Identity, Agent Gateway, Runtime/Sessions,
and Memory Bank remain unavailable unless independently proven otherwise. The
approved IAM/OIDC, private-ledger, versioned-card, and Spanner coordinator seams
must not be presented as those managed products.

## Prohibited fallbacks

Never present any of the following as managed or authoritative behavior:

- canonical Gemini fallback output;
- local substring filtering as Model Armor;
- canonical data after Spanner failure;
- static demo beats as SSE;
- in-memory reconciliation as Spanner Graph;
- HMAC as Cloud KMS; or
- configured resources as executed services.

Paid or mutable behavior must not hide behind a public health endpoint. Required
managed-path failure must fail closed and be reported truthfully.

## Evidence classifications

Every material implementation or acceptance claim must use exactly one of:

- `OBSERVED_LIVE`
- `MEASURED`
- `STRUCTURALLY_VERIFIED`
- `DESIGNED`
- `BLOCKED_WITH_TRUTHFUL_FALLBACK`
- `NOT_PROVEN`
- `FAILED`
- `ROADMAP`

Builder reports, screenshots, resource listings, configuration, and green unit
tests are not sufficient for independent managed-path acceptance. A configured
model is not an invocation; a published message is not a delivered callback; an
application response is not a Spanner mutation; and an application correlation
ID is not a Cloud Trace ID.

## Development safety

- Read this file, the relevant higher authority, and `git status` before edits.
  State the current gate and acceptance criteria. Preserve unrelated changes.
- Never destructively reset or reseed the shared canonical database. Tests use
  an isolated tenant, isolated database, or emulator. Production startup never
  seeds data.
- Use additive or reversible schema migrations. Treat schema/data uncertainty
  as an escalation, not permission to reset.
- Never expose credentials, secrets, raw identity tokens, sensitive prompts, or
  personal data in code, browser state, logs, traces, tests, or reports. Treat
  exposed secrets as compromised.
- Bind deployed images to the full Git SHA and use immutable image references.
- Commit precisely at every accepted work-package boundary. Local tests alone
  do not complete a managed-path package.
- Do not ignore root, nested, or local agent instruction files. A nested file
  may narrow implementation details but never weaken architecture, identity,
  mutation, scenario, or evidence rules.

## Required verification commands

Only checked-in, currently supportable commands are listed. Do not substitute a
legacy script for managed proof.

- Formatting/linting: `NOT YET AVAILABLE`.
- Safe unit tests:
  `PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src .venv/bin/python -m pytest -q packages/domain/tests/test_capacity.py packages/domain/tests/test_identity.py packages/domain/tests/test_incident_lifecycle.py packages/domain/tests/test_recall_reconciliation.py packages/domain/tests/test_tenant_isolation.py packages/domain/tests/test_truthful_terminal_state.py packages/domain/tests/test_ledger_commands.py packages/domain/tests/test_ledger_executor.py packages/domain/tests/test_authoritative_read_failures.py packages/domain/tests/test_single_mutation_authority.py apps/orchestrator/tests/test_ledger_identity.py apps/orchestrator/tests/test_no_authoritative_writes.py apps/plan-ledger/tests/test_ledger_auth.py apps/plan-ledger/tests/test_single_mutation_executor.py`
- Integration tests: `NOT YET AVAILABLE` until a non-shared isolated target is
  enforced. Do not use `scripts/run_tests.py` against canonical state.
- Safe test collection:
  `PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src .venv/bin/python -m pytest --collect-only -q packages/domain/tests apps/orchestrator/tests apps/plan-ledger/tests`
- Isolated WP2 mutation replay (requires `SPANNER_DATABASE_ID` to name a
  noncanonical database containing `audit`):
  `PYTHONPATH=packages/domain:packages/observability .venv/bin/python scripts/verify_wp2_isolated.py`.
  A complete isolated regression suite remains required in WP11.
- Deployment: `NOT YET AVAILABLE` as a checked-in end-to-end command. The
  SHA-parameterized `cloudbuild-orchestrator.yaml` and `cloudbuild-ledger.yaml`
  build images but do not deploy them.
- Managed-path replay: `NOT YET AVAILABLE`. Existing `scripts/test_deployed_slice.py`,
  `scripts/verify_part_a.py`, `scripts/verify_part_b.py`, and
  `scripts/verify_complete_product_loop.py` are legacy repair targets and are
  not acceptance evidence.

## Builder and auditor separation

Builders may implement, test, deploy, and report classified evidence. Builders
may not certify their own work. Final acceptance requires a different,
independent auditor. Frontend live wiring waits for independently accepted event
and projection contracts.

## Stop and escalate

Stop for an authority decision when a request conflicts with a higher authority,
the database or service behavior is ambiguous, a credential is exposed, a
demo-visible result would be fabricated, or a change would weaken tenant
isolation, authentication, approval binding, idempotency, deterministic policy,
zero-mutation refusal, or evidence truth.
