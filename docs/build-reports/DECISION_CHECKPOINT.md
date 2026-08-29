# AGENT CONTRACT V2 DECISION CHECKPOINT

**Date:** 2026-08-25  
**Repository:** `/private/tmp/full-shelf-demo-recovery`  
**Branch:** `release/full-shelf-demo-recovery`  
**Audit Source:** `/private/tmp/full-shelf-backend-event-audit`  
**Commission Phase:** Read-only discovery → decision checkpoint

---

## Executive Summary

The current five-agent fleet (Incident Coordinator, Recall Extraction, Network & Custody, Fulfillment Recovery, Partner Operations) has a sound architecture, truthful contracts, and verified isolation between advisory agents and the deterministic ledger mutation boundary. **The agent roster is load-bearing and must be preserved.** All five agents are operationally necessary and correctly scoped.

However, material truth gaps in the replay system and event model prevent acceptance in their current form without backend and replay implementation work. The coordinator implementation is correct; the specialist agents are correct; the issue is not agent design but event sequencing, session control, and replay contract enforcement.

**Verdict:** All five existing agents are `KEEP` with one recommendation: formally define the Incident Coordinator's role as orchestrator/supervisor, not a sixth specialist agent. Update naming/messaging to distinguish it from the specialist fleet clearly.

---

## Proposed Final Agent Roster

### 1. Incident Coordinator (Orchestrator)
**Role:** Supervisor of specialist sequence; non-agent sequencer role  
**JTBD:** Order the recall response sequence, validate each specialist's output against authoritative data before the next hop, and assemble a proposal that the deterministic ledger can accept or reject.  
**Current Status:** `KEEP`  
**Evidence:** 
- Clean ADK BaseAgent implementation with no ledger code or mutation authority.
- Coordinator clearly owns GOVERNED_SEQUENCE declaration.
- Delegation trace records both coordinator_run_id and specialist_run_id distinctly (no false parentage claims).
- All four specialists are built, not inherited; no transfer-to-parent/peers.
- Test `test_coordinator_holds_no_tools_and_no_ledger_code` verifies isolation.

**Implementation verdict:** No backend rewrite required. This is the accepted pattern.

---

### 2. Recall Extraction
**Role:** Specialist agent; structured extraction from Model-Armor-approved notice  
**JTBD:** Parse a sanitized recall notice and extract lot ID, hazard type, and affected locations using only the supplied text (never infer, never recall memory examples).  
**Current Status:** `KEEP`  
**Evidence:**
- Correct instruction forbidding inference and memory.
- Output schema (RecallExtractionSchema) is strict with source-anchor validation in `validate_recall_extraction`.
- No tools, deterministic decoding, temperature=0.
- Golden demo event `FS-E010-FACTS-EXTRACTED` correctly specifies "Lot LTC-4471, E. coli O157:H7; no invented RUNNING."
- Test audit shows atomic completion evidence only; no lifecycle intermediate state is expected.

**Implementation verdict:** No agent change. Backend must wire real event receipt for extraction start/completion if future lifecycle visibility is desired.

---

### 3. Network & Custody
**Role:** Specialist agent; custody graph traversal and containment assessment  
**JTBD:** Read the Spanner Graph for a recalled lot and report total cases, confirmed cases, unconfirmed downstream nodes, and a containment assessment (FULLY_TRACED or UNCONFIRMED_DOWNSTREAM).  
**Current Status:** `KEEP`  
**Evidence:**
- Correct instruction: "never compute, estimate, adjust; report only what tools show."
- Output schema (NetworkCustodyAssessment) forbids invented counts.
- Two tools: custody_graph_read and custody_dependents_read.
- Validation in `validate_custody_assessment` confirms every number matches graph output.
- Golden demo event `FS-E016-CUSTODY-RECONSTRUCTED` specifies "96 unique, 88 confirmed, 8 unconfirmed; Site 01 remains unconfirmed; no double count."

**Implementation verdict:** No agent change. Current tool design is sound and scoped correctly.

---

### 4. Fulfillment Recovery Planner
**Role:** Specialist agent; deterministic candidate selection  
**JTBD:** Choose one recovery plan from the deterministic candidate set (pre-computed by planning logic). Never modify quantities, destinations, or candidates. Prefer the candidate that serves the most agencies and leaves the smallest shortfall. Cite constraints honestly.  
**Current Status:** `KEEP`  
**Evidence:**
- Correct instruction forbidding mutation or invention.
- Output schema (RecoverySelection) requires rationale, cited_constraints, and tradeoffs.
- No tools; prompt contains the complete bounded candidate set.
- Validation in `validate_recovery_selection` confirms selected_candidate_id exists in the set and no quantities are claimed.
- Golden demo event `FS-E017-SAFE-RECOVERY-ALLOCATED` correctly shows "Exactly 40 replacement cases."

**Implementation verdict:** No agent change. Deterministic planner design is load-bearing and correct.

---

### 5. Partner Operations
**Role:** Specialist agent; template selection and message parameter binding  
**JTBD:** Choose one approved partner communication template and bind its required parameters. Never write prose, never acknowledge inventory, never confirm custody or close incidents. Evaluate confidence against a pre-known threshold and abstain if unsure.  
**Current Status:** `KEEP`  
**Evidence:**
- Correct instruction: "select one template_id, supply exact required parameters copied from partner state, never write prose."
- Output schema (PartnerCommunication) includes template_id, template_parameters, escalation_level, and confidence.
- No tools; prompt contains partner_state_read() output and PARTNER_TEMPLATE_IDS.
- Validation in `validate_partner_communication` recomputes escalation level from trusted partner state and rejects agent disagreement.
- Golden demo shows both vague and complete proof handling as isolated lenses, not as agent state.

**Implementation verdict:** No agent change. Template-first design is correct.

---

## Detailed Classification

| Agent ID | Current Impl | Role | JTBD | Classification | Reasoning | Backend Work |
|---|---|---|---|---|---|---|
| `full-shelf.incident-coordinator.v1` | BaseAgent subclass; governs sequence | Orchestrator/supervisor | Order response sequence, validate hops, assemble proposal | `KEEP` | Clean separation from ledger; no invoked tools; delegation trace correct; test isolation verified | None required; wiring only |
| `full-shelf.recall-extraction.v1` | LlmAgent; zero tools; temp=0 | Specialist | Extract lot/hazard from sanitized notice | `KEEP` | Sound schema validation; no inference; instruction correct; output schema enforced | Event receipt for extraction completion |
| `full-shelf.network-custody.v1` | LlmAgent; two graph tools | Specialist | Assess custody containment from Spanner Graph | `KEEP` | Tools are read-only; validation enforces number matching; instruction forbids computation | No agent change needed |
| `full-shelf.fulfillment-recovery.v1` | LlmAgent; zero tools | Specialist | Select one deterministic candidate | `KEEP` | Candidate set pre-computed; instruction forbids mutation; schema forbids quantity claims | No agent change needed |
| `full-shelf.partner-operations.v1` | LlmAgent; zero tools | Specialist | Select template and bind parameters | `KEEP` | Template and parameter binding enforced; escalation level recomputed deterministically; confidence gated | No agent change needed |

---

## Material Truth Gaps (Audit Findings)

These are **blocking replay acceptance** but do **not require agent redesign**:

### 1. **Morning Plan Generation Provenance** (Event `FS-E001`)
- **Finding:** Replica fixture shows rev07 already SUPERSEDED at 08:05; no replay event for 05:30 generation or 06:45 approval.
- **Implication:** Frontend props read generation/approval timestamps from projection, but no business event triggered them.
- **Root Cause:** Replay fixture selector, not a sequencer; generation happens "off-stage."
- **Fix Required:** Backend must emit `PLAN_GENERATION` and `PLAN_APPROVAL` receipts during real planning/approval flows. Replay must reproduce these events before day opening.
- **Agent Impact:** None. Coordinator is triggered downstream.

### 2. **Approval Flow Broken in Replay** (Event `FS-E006`)
- **Finding:** Frontend POST `/api/v1/orchestrator/approvals/approve-and-activate` returns HTTP 501 "Unsupported method."
- **Implication:** Tests intercept and fake HTTP 200; real replay cannot accept approval.
- **Root Cause:** Replay server has no `do_POST` implementation; approval is backend-only today.
- **Fix Required:** Replay must implement synthetic approval acceptance (test use only) with idempotency and proper session isolation. Real approval remains KMS-bound in production.
- **Agent Impact:** None. Coordinator does not call approval; it consumes the approved state.

### 3. **Plan Invalidation Not Reflected in Projection** (Event `FS-E014`)
- **Finding:** `INVALIDATE_PLAN` receipt appears in ledger at 10:07, but projection at 10:10+ still shows rev08 ACTIVE instead of INVALIDATED.
- **Implication:** Courier read projection contracts do not apply the invalidation mutation.
- **Root Cause:** Projection schema or validator does not consume the invalidation receipt.
- **Fix Required:** Projection must consume all mutating receipts in order and apply them. Validation should assert consistency.
- **Agent Impact:** None. Agents read deterministic state; this is presentation.

### 4. **Agent Lifecycle Atomicity in Replay** (Events `FS-E015`, `FS-E016`, `FS-E017`)
- **Finding:** All five agents (four specialists + coordinator result aggregate) appear atomically as COMPLETED at 10:10. No RUNNING, WAITING, or intermediate state is persisted.
- **Implication:** Replay cannot show agent execution progress. UI shows "ESTABLISHED" but no started_at, duration, or failure states.
- **Root Cause:** Fixture model captures only terminal state. ADK event stream was not persisted for intermediate events.
- **Fix Required:** If lifecycle visibility is desired, backend must persist `agent_started`, `agent_awaiting_tool`, and `agent_completed` events and replay must surface them correctly. Current acceptance is atomic only.
- **Agent Impact:** Agents produce correct terminal output. The missing detail is lifecycle visualization, not agent correctness.

### 5. **Event Sequencing Not Enforced in Replay** (All events)
- **Finding:** Replay has no session sequencer; browser navigation with ArrowRight and tab clicks select time arbitrary. Events fire in arbitrary order via presenter control.
- **Implication:** Frontend can reach rev08 without approval, navigate from 10:19 back to 10:13, request Saturday draft at 08:05.
- **Root Cause:** Replay is a fixture selector (`as_of` parameter), not a sequencer. No start, advance, pause, reset, or idempotency route exists.
- **Fix Required:** Replay must implement session-scoped sequencing with cursor and event list. Start/advance/reset controls must enforce event ordering. Proof selection must be isolated.
- **Agent Impact:** None. Coordinator runs once per incident; sequencing is infra, not agent.

---

## Recommendations to Product Owner

### Question 1: Should the Incident Coordinator be renamed or reclassified?
**Current terminology confusion:** The coordinator is called an "agent" but it is actually an orchestrator/supervisor. It owns the sequence and validation logic, not a specialist function.

**Recommendation:** Rename `AGENT_INCIDENT_COORDINATOR` to `ORCHESTRATOR_INCIDENT_COORDINATOR` or introduce a `ComponentKind.ORCHESTRATOR` in the contracts. Keep the agent object itself; change the framing. This removes the false claim that there are "five specialist agents"; there are **four specialists + one orchestrator**.

**Implication if approved:** Update agent ID, test labels, and catalog. No code change to coordinator logic.

---

### Question 2: Is the atomic agent lifecycle acceptable for the golden demo?
**Current state:** All agents appear COMPLETED at 10:10. No intermediate RUNNING record is persisted.

**Recommendation:** Accept atomic completion for the demo. If full lifecycle visibility is desired later, add event persistence. The agent code is correct; the fixture is intentionally simplified for deterministic demo purposes.

**Implication if approved:** Replay SSE can report agent completion; do not try to synthesize RUNNING from elapsed time or heartbeats.

---

### Question 3: Should replay approval be wired for the demo?
**Current state:** Real approval works in production (KMS-signed); replay has no approval POST route.

**Recommendation:** Implement a synthetic, test-only approval route in replay that is clearly labeled as synthetic. Accept the approval, idempotently persist a synthetic receipt, and advance to rev08. Never present synthetic approval as evidence of real KMS/Google workload verification.

**Implication if approved:** Replay can demonstrate the full flow end-to-end. Production approval remains in the orchestrator.

---

### Question 4: Should plan invalidation affect projection immediately or remain "advisory"?
**Current state:** Receipt exists at 10:07, but projection shows ACTIVE through 17:00.

**Recommendation:** Projection must consume invalidation receipts and show rev08 INVALIDATED from 10:07 onward. "Advisory" state is not acceptable in a deterministic ledger; the authorization either happened or did not.

**Implication if approved:** Projection contract must include all mutating receipts in order.

---

### Question 5: Is the isolated-proof model correct for vague/complete partner evidence?
**Current state:** Vague proof (10:16) and complete proof (10:19) are read-only isolated lenses. Canonical remains 88/96; isolated proof selection does not rewrite history.

**Recommendation:** This is correct. Isolated proofs are **not agent executions**, they are operator-selected reference lenses into conditional states. They must never become canonical and must not rewrite history. The partner_operations agent is not re-invoked; the operator is selecting an evidence scenario.

**Implication if approved:** Proofs remain isolated; no agent re-runs on proof selection. Vague/complete are demo-scenario variants, not agent outcomes.

---

## Backward-Compatibility & Continuity

- **Existing agent code:** All five agents pass isolation tests and schema validation. No rewrite required.
- **Existing coordinator topology:** Separate-runner topology with explicit correlation is correct. No refactor needed.
- **Existing validation:** All `validate_*` functions in `validation.py` remain load-bearing. Preserve them.
- **Existing Spanner schema:** Unchanged.
- **Existing model ID:** Remains `gemini-3.5-flash` as authoritative identity. The `gemini-flash-latest` alias in fixtures is acceptable for demo.

---

## Files to Retain Unchanged

- `packages/domain/full_shelf_domain/fleet/agents.py` — All five builders are correct.
- `packages/domain/full_shelf_domain/fleet/coordinator.py` — Orchestration logic is correct.
- `packages/domain/full_shelf_domain/fleet/contracts.py` — All schemas and identities are load-bearing.
- `packages/domain/full_shelf_domain/fleet/validation.py` — All deterministic validators are correct.
- `packages/domain/tests/test_fleet_agents.py` — All isolation tests pass and should remain.
- All ADR documents (001–010) — Decisions remain valid.
- `docs/authority/resolved-baseline.md` — Authority is unchanged.

---

## Explicit Out-of-Scope for Phase 1

- **Do not modify agent logic.** The agents are correct.
- **Do not add a sixth agent.** Model Armor is a boundary, not an agent. Deterministic ledger is infra, not an agent.
- **Do not invent agent lifecycle state.** No RUNNING without a persisted start record.
- **Do not change Spanner schema.** Unchanged.
- **Do not implement Google Maps work.** Separate scope.

---

## Final Verdict

**All five agents are KEEP. No redesign required. No roster change.**

The issues identified in the audit are **replay control, event sequencing, and projection consistency**, not agent design. The coordinator is correctly a supervisory orchestrator, not a specialist. The four specialists are correctly scoped and isolated.

Proceed to **Phase 2: Agent Contract V2** with the understanding that:
1. Agent roster is stable.
2. Orchestrator is distinct from specialists (may rename for clarity).
3. Backend event creation and replay sequencing are the load-bearing work.
4. Replay must implement session control, approval acceptance, and idempotent event replay.
5. Projection must consume all mutating receipts in order.

---

## Repository Integrity Confirmation

- **Source repository:** `/private/tmp/full-shelf-demo-recovery`
- **Branch:** `release/full-shelf-demo-recovery`
- **SHA:** `ce876c26e6cdbf30c47ac96427e74bf6831bbf02`
- **Worktree status:** CLEAN (no changes during this commission)
- **Audit artifacts location:** `/private/tmp/full-shelf-backend-event-audit`

No source code modified. This document is the sole output of Phase 1.

---

## Decision Gates for Phase 2

This checkpoint is **ready for product-owner approval**. The five recommended questions above represent the product decisions needed before Phase 2 (Agent Contract V2 + Event Contract + Implementation Delta).

If approved, proceed to create:
1. `docs/strategy/AGENT_CONTRACT_V2.md` — Detailed per-agent specifications
2. `docs/strategy/GOLDEN_DEMO_EVENT_CONTRACT.md` — Chronological event model
3. `docs/strategy/CONTRACT_V2_IMPLEMENTATION_DELTA.md` — Replay, backend, and frontend work list
