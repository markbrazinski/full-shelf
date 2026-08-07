# Full Shelf Permanent Coding-Agent Constitution

This document serves as the repository-level coding-agent constitution for Full Shelf. It prevents architectural drift, unsupported completion claims, security mistakes, and changes to the locked demo truth.

## 1. Product and demo authority

- **Product**: Full Shelf.
- **Category**: Food-bank fulfillment control plane.
- **Canonical product authority**: The Full Shelf Build Book.
- **Core Thesis**: The product repairs ordinary distribution disruptions and later revises its own work when new safety evidence makes the prior plan false.
- **Authority Rule**: Do not silently modify the thesis, demo spine, architecture boundary, canonical quantities, IDs, or terminal state.
- **Change Management**: Material changes require an explicit change request.

## 2. Canonical scenario

- **Recalled lot**: LTC-4471.
- **Safe lot**: LTC-5090.
- **Hazard**: E. coli O157:H7.
- **Source plan revision**: rev07.
- **Repaired plan revision**: rev08.
- **Order Reroutes**:
  - O202: 22 cases rerouted to Truck 2.
  - O203: 20 cases converted to refrigerated partner pickup.
- **Vehicle Capacities**:
  - Truck 2 capacity: 60.
  - Existing load: 36.
  - Both stranded orders cannot fit because 36 + 22 + 20 = 78.
- **Physical recall positions**: 24 (Warehouse) + 22 (Truck 2) + 20 (Staging O203) + 10 (Agency 01) + 8 (Site 01) + 12 (Rescue) = 96.
- **Downstream Deduplication**: Site 01’s eight cases are a subset of Agency 01’s historical delivery and must never be double-counted.
- **Safe replacement allocation**: 18 (Agency 01) + 22 (Agency 02) = 40.
- **Shortfall**: Agency 03 ends with a 20-case shortfall.
- **Terminal state**: PARTIALLY_CONTAINED.
- **Unconfirmed Cases**: Site 01 remains unconfirmed with eight cases.

## 3. Incident lifecycle

Only allow the following explicit state transitions:

```
DETECTED
  → SCOPING
  → CONTAINMENT_IN_PROGRESS
  → PARTIALLY_CONTAINED
  → CONTAINED
  → CLOSED
```

`PARTIALLY_CONTAINED` may only be entered after:
- all 96 physical cases are traced;
- known unsafe movements are blocked;
- safe replacements are allocated;
- 88 cases are confirmed;
- eight Site 01 cases remain unconfirmed;
- false containment is refused.

Incident creation must not immediately set a terminal state.

## 4. Google technology requirements

- **Gemini Version**: Submitted runtime must use Gemini 3.5 or newer (`gemini-3.5-flash` or higher).
- **Model Check**: Fail tests and deployment if the configured Gemini model is older than 3.5.
- **Agent Framework**: Google ADK is the agent framework.
- **Gemini Role**: Gemini performs interpretation, planning, and source-anchored extraction.
- **State Mutation Rule**: Gemini may never directly mutate authoritative state.
- **Model Armor**: Model Armor screens untrusted recall input before Gemini.
- **Spanner Authority**: Spanner is authoritative for plans, incidents, custody, approvals, commands, receipts, checkpoints, and work items.
- **Spanner Graph**: Spanner Graph performs custody and dependency traversal.
- **Pub/Sub**: Pub/Sub wakes the persisted coordinator.
- **Cloud Tasks**: Cloud Tasks schedules durable acknowledgment escalation.
- **Cloud KMS**: Cloud KMS signs and verifies complete approval envelopes.
- **Cloud IAM**: Cloud IAM, service accounts, and OIDC enforce workload identity.
- **Cloud Trace**: OpenTelemetry exports real traces to Cloud Trace.

## 5. Service boundaries

**orchestrator**:
- Cloud Run service.
- Read-only Spanner access.
- Gemini and ADK execution.
- Model Armor boundary.
- Invokes `plan-ledger` with workload OIDC.
- No authoritative write capability.

**plan-ledger**:
- Private Cloud Run service.
- Only deterministic mutation authority.
- Validates policy, signatures, revision preconditions, tenancy, and idempotency.
- Owns Spanner writes and mutation receipts.

Do not collapse these services.
Do not add the roadmap partner-edge service during the hackathon without explicit approval.

## 6. Approval invariant

The rev08 approval envelope binds:
- source revision rev07;
- proposed revision rev08;
- complete canonical plan diff;
- O202 action and quantity;
- O203 action and quantity;
- approver principal;
- incident ID;
- expiration;
- plan-diff SHA-256;
- KMS key version.

Changing any bound value must invalidate verification and cause zero mutations.

## 7. Security rules

- Never commit or print credentials.
- Never place secrets in React client code.
- Use Secret Manager for runtime secrets.
- Treat any secret shown in chat, logs, documentation, test output, or git as compromised and rotate it immediately.
- Never expose `plan-ledger` publicly.
- Public health endpoints must not trigger paid or mutable behavior.
- Tenant identity comes from authenticated context, not a request-body override.
- Scrub tokens, raw sensitive prompts, and personal data from traces.

## 8. Evidence discipline

Every material claim must be labeled as one of:
- `OBSERVED_LIVE`
- `MEASURED`
- `STRUCTURALLY_VERIFIED`
- `DESIGNED`
- `ROADMAP`
- `BLOCKED_WITH_TRUTHFUL_FALLBACK`

Never claim:
- a configured model was invoked without a managed invocation receipt;
- a correlation ID is a Cloud Trace ID;
- an application response proves a Spanner mutation;
- a published Pub/Sub message proves coordinator wake/resume;
- a local adapter is a managed Google service;
- a representative notice is a real government notice;
- a phase is complete while its exit test is incomplete.

## 9. Managed preview services

Managed Agent Registry, Agent Identity, Agent Gateway, Agent Runtime/Sessions, and Memory Bank were unavailable or blocked in the project.

Use and label the approved seams:
- versioned Agent Cards/tool manifest;
- Cloud IAM and OIDC;
- private `plan-ledger` policy gateway;
- Spanner-backed coordinator state.

Do not represent these seams as the managed preview services.
Memory Bank must never hold authoritative inventory, custody, plan, incident, approval, or receipt state.

## 10. Implementation protocol

Before editing:
- read `AGENTS.md`;
- read the relevant Build Book sections;
- inspect git status;
- preserve unrelated changes;
- state the current gate and acceptance criteria.

After editing:
- run relevant unit, contract, integration, and deployed tests;
- reconcile state directly from authoritative services;
- report changed files;
- report test evidence;
- report managed-resource evidence;
- report limitations;
- commit with a precise message.

Do not call a task complete merely because tests pass locally.

## 11. Required hero-loop exit test

The backend hero loop is complete only when a deployed replay proves:

`rev07`
→ truck disruption
→ KMS-approved `rev08`
→ persisted `WAITING_FOR_EVENTS`
→ process replacement
→ Pub/Sub recall wake
→ Model Armor
→ Gemini 3.5+ through ADK
→ Spanner Graph 96-case reconstruction
→ recalled-lot barrier
→ `rev08` invalidation
→ 40-case safe recovery
→ 20-case shortfall
→ false-containment denial with zero mutations
→ Cloud Task scheduled
→ `PARTIALLY_CONTAINED`

The same coordinator, incident, action, receipt, and real Cloud Trace identifiers must correlate across the path.

## 12. Frontend contract

- Preserve the approved Claude Design visual system.
- Frontend states must come from versioned backend projections.
- Do not animate a completed result as though live work is still occurring.
- Do not show managed proof badges before the corresponding evidence exists.
- Never hide a secret in the browser.
- Keep service and safety outcomes visually distinct.

## MUST NOT

- Modify the locked scenario for coding convenience.
- Downgrade Gemini below 3.5.
- Hardcode successful terminal results.
- Bypass `plan-ledger` for writes.
- Treat UI state as operational authority.
- Invent managed-service evidence.
- Expand scope merely because implementation is ahead of schedule.
- Add `AGENTS.md` or `GEMINI.md` to any ignore file.

## PREFERENCES

- Contract-first changes.
- Deterministic mutation code.
- Small, reviewable commits.
- Explicit state machines.
- Direct managed-service verification.
- One authoritative fixture source.
- Clear failure and refusal behavior.
- Proof depth over feature breadth.

## ESCALATE

- A requested change conflicts with `AGENTS.md` or the Build Book.
- The authoritative database is ambiguous.
- A required managed service behaves differently from the documented contract.
- A credential is exposed.
- A demo-visible value would need to be fabricated or hardcoded.
- A change would weaken tenant isolation, approval binding, idempotency, or evidence truth.
