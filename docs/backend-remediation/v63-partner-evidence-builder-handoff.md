# V6.3 partner evidence builder handoff

Recorded: 2026-08-24 (America/Los_Angeles)

Frozen implementation commit: `055ef231cd29dd289c02edd151c832fa162c4266`

Base and merge base: `9e9d7fd8a882b751999e317ee607c5d76e5900e4`

Branch: `feat/v6-3-partner-evidence-codex`

Classification: builder testimony; independent acceptance required

This handoff records the completed local implementation boundary. It does not
claim managed-path or production acceptance. The builder did not merge, push,
deploy, or access canonical cloud state. The pre-existing dirty checkout was
not used for implementation and was not modified.

## Implemented boundary

- `STRUCTURALLY_VERIFIED` — `POST /api/v1/orchestrator/partner-evidence` is
  classified `PARTNER_CALLBACK` in the default-deny matrix and derives tenant
  and partner scope from an exact verified callback-principal mapping. Its
  request contract accepts only the constant event type, source-event ID,
  incident ID, original text, and timezone-aware occurrence timestamp.
- `STRUCTURALLY_VERIFIED` — the strict
  `partner-custody-confirmation.v1` work-item details model requires every
  approved field and forbids extras. `RECORD_ACKNOWLEDGMENT_HOLD` creates the
  open typed work item transactionally and derives its ID once at creation.
- `STRUCTURALLY_VERIFIED` — the Partner Operations task uses the existing
  `full-shelf.partner-operations.v1` identity, a real ADK 2.6.1 `Runner`, a real
  `InMemorySessionService`, and a strict proposal schema. Tests stub the model
  response below the Runner while exercising session creation and the event
  loop. Only emitted session, invocation, and final-event identifiers persist;
  no parallel run ID exists.
- `STRUCTURALLY_VERIFIED` — deterministic policy rechecks every literal quote,
  quoted value, authoritative target, quantity, state, and the exact
  `ISOLATED_IN_QUARANTINE` disposition. Confidence has no authorization role.
- `STRUCTURALLY_VERIFIED` — `PROCESS_PARTNER_EVIDENCE` is restricted to
  `PARTNER_OPERATIONS_AGENT`. The outer executor computes the receipt ID once,
  passes it as transaction context, and inserts the only receipt after the
  handler returns mutation accounting. The evidence handler never creates a
  receipt or derives a replacement ID.
- `STRUCTURALLY_VERIFIED` — identical replay returns the original receipt and
  accounting. Reuse of the source-event identity with changed source hash,
  occurrence, incident, or partner is a permanent HTTP 409 with zero writes.
- `STRUCTURALLY_VERIFIED` — the operator projection remains `HUMAN_OPERATOR`
  with `require_frontend_authority`. It exposes bounded partner evidence only
  through that route. SSE transports only a committed receipt cursor; live UI
  code refetches the authenticated projection instead of receiving material
  evidence in the stream.
- `STRUCTURALLY_VERIFIED` — the main twelve replay beats retain the canonical
  88/96 and `PARTIALLY_CONTAINED` truth. Vague 10:15/10:16 and complete
  10:18/10:19 proofs are separate non-timeline boundaries explicitly labeled
  `ISOLATED_SELECTED_PROOF`.

## Measured local evidence

- `MEASURED` — safe collection: 565 tests collected, preserving the previous
  554-test collection and adding V6.3 coverage.
- `MEASURED` — constitution suite: 96 passed.
- `MEASURED` — focused contracts, V6.3, bounded projection, authentication,
  and replay suite: 235 passed.
- `MEASURED` — final repository suite: 630 passed, 1 skipped.
- `MEASURED` — final SSE/projection/replay selection: 179 passed.
- `MEASURED` — the official Spanner emulator accepted both the consolidated
  schema and the pre-V6.3 schema plus migration. On each database, the isolated
  verifier produced a vague `DENIED` result at 88 confirmed cases with an open
  work item and zero domain mutations, followed by a complete `SUCCESS` at 96
  confirmed cases with the exact work item completed and two domain mutations.
  Each path wrote one evidence row and one linked receipt; replay added no row.
- `MEASURED` — web TypeScript checking and the production Vite build passed.
- `MEASURED` — all 26 configured Playwright cases passed with one worker at the
  configured 1600×900 viewport, including the vague and complete proof views.
- `MEASURED` — `git diff --check` passed at every commit boundary.

## Evidence limits

- `NOT_PROVEN` — no live Google-signed partner callback was sent.
- `NOT_PROVEN` — no managed Model Armor call or live Gemini model response was
  executed for V6.3. Local tests exercise the genuine integration boundaries
  and real ADK Runner with a deterministic underlying model stub.
- `NOT_PROVEN` — no Cloud Run revision, IAM binding, managed delivery, Cloud
  Trace span, or canonical Spanner mutation was inspected or changed.
- `DESIGNED` — deployment-owned callback audience, subject, email, and
  subject-to-tenant/partner mappings must be supplied by the deployment before
  the route can accept a callback.

The independent auditor must reproduce the commission in
`docs/operations/v63-partner-evidence-independent-audit.md` from the frozen
implementation commit. Builder results and screenshots are not acceptance.

