# Agent Contract V2 — agent-layer conformance

**Date:** 2026-08-25
**Branch:** main
**Verdict claimed:** `AGENT_LAYER_GOLDEN_PATH_CANDIDATE`
**Prepared by:** builder (non-authoritative testimony per `AGENTS.md`)

This is a builder report. It is not an acceptance certification, and it does
not claim production readiness. Independent audit is required.

## Scope

Backend agent, coordinator, and validator layer only. This report does **not**
claim `FILMABLE_GOLDEN_PATH_ACCEPTED`; replay/session mechanics, canonical
versus isolated cursor behavior, SSE monotonicity, and all frontend work remain
outside it and are itemized under Deferred below.

## What preceded this

An earlier attempt reported eight findings complete and "production-ready" on
the strength of one passing test file. Repository-wide it had introduced 29
failures, including a schema change that broke the vague-partner refusal in
production. That work was reverted commit-by-commit and re-implemented here.

Every commit in this commission verifies **repository-wide** before landing.

## Findings

| ID | Defect | Resolution |
|---|---|---|
| F10 | `_RECALL_SEQUENCE` hand-copied the recall path and disagreed with `ORCHESTRATION_PATHS` after it changed | Sequence derived from one authoritative source; §6 recall path is four agents; `PARTNER_CALLBACK` removed as a fleet trigger |
| F5 | Recall extraction never checked `source_event_id`, and checked quotes without checking that values derived from them | Both required; a real quote can no longer launder a fabricated value |
| F1 | Handlers passed candidate metadata only; two bare-subscript lookups raised `KeyError` masked as `FLEET_EXECUTION_FAILED`; validator demanded shortfalls universally | Three objective-specific categories at all three call sites; at least one required; a partner pickup is no longer miscounted as a shortfall |
| F9 | Next-day handler test failed | Resolved by F1 — the failure was the daily-plan gate, not Gemini scripting |
| F8 | Any missing partner claim did not force abstention | Missing claims normalize to `abstain=True` with no mutation request, so the refusal is **persisted** rather than rejected at the schema layer |
| F6 | Custody positions, commitments, and obligations were skipped when empty; the node universe defaulted to empty and condemned honest positions as fabricated | All three required; `CUSTODY_GRAPH_UNIVERSE_MISSING` separates a missing input from a fabrication finding |
| F2 | Incident Lead authorization ran **after** every specialist had executed | Enforced at dispatch: an unauthorized specialist is never constructed or invoked. Bare reason code with IDs in their own field; no longer fails open on falsy output |
| F7 | The revision precondition was dead in every production path | Threaded through `run_fleet` and `FleetRunContext`; all three handlers pass their expected revision |
| F12 | The Saturday draft carried three of event 25's four obligations | `UNRESOLVED_INCIDENT` added; the test asserts the obligation **set**, not positions |
| F4 | Incident Lead prompt read three deleted V1 fields and rendered `"unknown"` for every one | Reads V2 `{value, quote}` claims |
| F11 | Partner-evidence isolation does not exist | **Deferred**, documented in `docs/operations/partner-evidence-isolation-interface.md` |

Also fixed: a production `TypeError` reading `proposal["partner"]["template_id"]`
unconditionally after Partner Operations correctly stopped running on the recall
path.

## Test evidence

`STRUCTURALLY_VERIFIED` — real ADK runtime with only the Gemini network call
scripted. Not live-model evidence.

- Repository-wide: **607 passed, 1 skipped, 0 failed**
- `AGENTS.md` safe unit suite: **96 passed**

Guards verified by mutation — disabling each turns its test red, proving it
detects regressions rather than passing incidentally:

- F7's revision precondition (unwiring the call site)
- Approval not-found and plan-diff-hash-mismatch refusals

## Canonical values

Unchanged and re-asserted: custody `24+22+20+10+8+12 = 96` unique / `88`
confirmed / `8` unconfirmed; recovery `40` safe (`18`+`22`) with a `20`-case
Agency 03 shortfall; Truck 2 at `58/60` after rev08.

The altered-hero test reconciles a different set (`46+5 = 51`), proving these
checks are computed rather than remembered.

## Deferred — named, not silent

**Golden Runtime Controller** (submission-blocking for the filmable gate):
partner-evidence write isolation (F11); isolated branch versus canonical cursor
(§8.10–8.11); replay session isolation and reset (§8.1–8.3); gap-free ordinal
sequence per session (§8.14); frontend approval and alert behavior (§9).

**P2:** daily-morning-plan candidate genuineness; `cited_constraints` catalog
validation; Model Armor managed-execution proof (`NOT_PROVEN` stands).

**Already satisfied, verified this commission:** server-side future-state
exclusion (§8.9); altered-approval denial with zero mutation (§10.4); SSE never
carrying raw source text (§10.2); event 9 → event 10 approval invariant.

## Agent authority invariant

Intact and tested: no agent can mutate authoritative state. Agents propose,
deterministic policy decides, the private ledger commits.
(`test_single_mutation_authority.py`, `test_no_authoritative_writes.py`)
