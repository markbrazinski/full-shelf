# Full Shelf Golden Demo Event Contract

**Status:** Authoritative strategy contract — ready for product-owner lock  
**Date:** 2026-08-25  
**Canonical operating day:** Friday, 2026-08-14  
**Next-day draft:** Saturday, 2026-08-15  
**Purpose:** One event graph for managed execution, deterministic replay, frontend state, filming, and judge access

## 1. Demo contract

By the end of the video, a food-bank operations director will have seen Full Shelf preserve service through a refrigeration failure, reconstruct a recalled lot across 96 unique cases, refuse vague partner evidence without corrupting state, and demonstrate that complete evidence can resolve the exact eight-case custody gap—while deterministic policy, human approval, KMS, and the private ledger retain authority over what becomes true.

The canonical filmed timeline ends at:

- incident `INC-2231` = `PARTIALLY_CONTAINED`;
- custody = `88 / 96` confirmed;
- Site 01 = eight cases unconfirmed;
- safe replacements = 40;
- Agency 03 shortfall = 20;
- rev08 invalidated by the recall;
- Saturday draft = `DRAFT_WITH_CONSTRAINTS` carrying all unresolved obligations.

The complete partner response is an isolated proof branch. It never silently rewrites that canonical ending.

## 2. Locked scenario data

### Friday rev07

Truck 1, refrigerated, capacity 60:

- O201 → Agency 01: 18 cases LTC-4471; delivered before the failure;
- O202 → Agency 02: 22 cases LTC-4471;
- O203 → Agency 03: 20 cases LTC-4471.

Truck 2, refrigerated, capacity 60:

- O204 → Agency 04: 15 cases LTC-5090;
- O205 → Agency 05: 21 cases LTC-5090;
- assigned 36; spare 24.

### rev07 → rev08 repair

- O202 moves to Truck 2: `36 + 22 = 58 / 60`;
- O203 becomes refrigerated partner pickup because the additional 20 cases do not fit;
- activation requires one verified-human approval bound to the exact diff.

### Recalled-lot positions

| Position | Cases |
| --- | ---: |
| Warehouse | 24 |
| Truck 2 / O202 | 22 |
| Partner or pickup staging / O203 | 20 |
| Agency 01 retained | 10 |
| Site 01 downstream | 8 |
| Direct-rescue recipient | 12 |
| **Unique total** | **96** |

Agency 01 originally received 18 and forwarded eight to Site 01. Those eight are not additional physical inventory.

## 3. Event envelope

Every managed or replay event uses the following logical envelope:

```json
{
  "schema_version": "full-shelf.demo-event.v2",
  "event_id": "stable scenario event ID",
  "event_type": "string",
  "scenario_id": "full-shelf-friday-2026-08-14",
  "session_id": "opaque session ID",
  "sequence": 0,
  "effective_at": "ISO-8601 scenario time",
  "recorded_at": "ISO-8601 trusted or replay time",
  "trigger_class": "AUTONOMOUS_SCHEDULED | AUTONOMOUS_CHAINED | EXTERNAL_EVENT | HUMAN_GATE | ISOLATED_PROOF | NAVIGATION_ONLY",
  "authority": "CANONICAL | ISOLATED",
  "actor": {"kind": "SYSTEM | AGENT | HUMAN | EXTERNAL", "id": "string"},
  "correlation": {
    "tenant_id": "string",
    "operating_day": "2026-08-14",
    "plan_id": "PLAN-2026-08-14",
    "incident_id": "string|null",
    "source_event_id": "string|null",
    "agent_run_id": "string|null"
  },
  "source_refs": ["string"],
  "payload": {},
  "validation": {"status": "ACCEPTED | DENIED | FAILED", "reasons": ["string"]},
  "receipt_refs": ["string"],
  "projection_delta": {},
  "activity_entry": {
    "severity": "INFO | ATTENTION | CRITICAL | SUCCESS | REFUSAL",
    "headline": "string",
    "detail": "string",
    "action_required": false
  },
  "evidence_classification": "OBSERVED_LIVE | MEASURED | STRUCTURALLY_VERIFIED | SYNTHETIC_TEST"
}
```

SSE may transmit the envelope, cursor, and bounded projection signal. It must not stream raw untrusted source text.

## 4. Trigger classes

| Trigger | Meaning |
| --- | --- |
| `AUTONOMOUS_SCHEDULED` | Initiated by an accepted scheduled trigger. |
| `AUTONOMOUS_CHAINED` | Permitted only after its predecessor commits or establishes accepted evidence. |
| `EXTERNAL_EVENT` | Accepted from fleet telemetry, regulatory feed, or authenticated partner callback. |
| `HUMAN_GATE` | Requires an explicit authorized human action; autoplay cannot cross it. |
| `ISOLATED_PROOF` | Executes in a session branch that cannot mutate the canonical cursor or tenant history. |
| `NAVIGATION_ONLY` | Changes the viewed surface only; never changes scenario time or business state. |

## 5. Canonical event set

| Seq | Stable event ID | Effective time | Trigger | Actor / agent | Accepted outcome | Canonical mutation and visible consequence |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `FS-E001-PLAN-GENERATION-TRIGGERED` | 05:30 | `AUTONOMOUS_SCHEDULED` | Scheduler / orchestrator | Candidate generation begins from current constraints. | No mutation. Historical Activity entry only. |
| 2 | `FS-E002-REV07-PROPOSED` | 05:30 | `AUTONOMOUS_CHAINED` | Fulfillment Planning & Recovery | Selects the deterministically feasible rev07 candidate for five stops and 96 cases. | rev07 stored as `PROPOSED`; proposal receipt; no activation. |
| 3 | `FS-E003-REV07-APPROVED` | 06:45 | `HUMAN_GATE` | Verified operations director | Exact rev07 candidate approved and KMS-bound. | Approval receipt; rev07 remains not active until scheduled activation. |
| 4 | `FS-E004-REV07-ACTIVATED` | 07:30 | `AUTONOMOUS_CHAINED` | Private ledger | Approved rev07 becomes authoritative. | rev07 `ACTIVE`; five commitments and manifests authoritative. |
| 5 | `FS-E005-DAY-OPENED` | 08:05 | `AUTONOMOUS_SCHEDULED` | Operating clock / projection | Healthy Friday opening becomes the current judge/film boundary. | No new operational mutation. Today shows five stops, 96 cases, Truck 2 `36/60`. No Saturday state. |
| 6 | `FS-E006-REFRIGERATION-FAILURE-RECEIVED` | 08:20 | `EXTERNAL_EVENT` | Simulated fleet telematics | Truck 1 refrigerated capability is unavailable. | Vehicle incident `INC-2210` opens; alert appears at page top, on Truck 1, and in Activity. Not inferred from GPS. |
| 7 | `FS-E007-FLEET-INCIDENT-SCOPED` | 08:20 | `AUTONOMOUS_CHAINED` | Incident Lead | Establishes cold-chain capability loss, remaining affected commitments O202/O203, and recovery playbook. | Validated incident scope is persisted; Activity shows what the agent established. |
| 8 | `FS-E008-REV08-REPAIR-PROPOSED` | 08:21 | `AUTONOMOUS_CHAINED` | Fulfillment Planning & Recovery | Selects O202 → Truck 2 and O203 → refrigerated partner pickup. | Exact rev07→rev08 diff stored as `PROPOSED`; approval surface appears above the fold; rev07 remains authoritative. |
| 9 | `FS-E009-REV08-REPAIR-APPROVED` | 08:24 | `HUMAN_GATE` | Verified operations director | One click approves the exact diff once. | KMS-bound approval receipt. Duplicate is idempotent; altered binding is denied with zero mutation. |
| 10 | `FS-E010-REV08-ACTIVATED` | 08:24 | `AUTONOMOUS_CHAINED` | Private ledger | Approved repair activates atomically. | rev08 `ACTIVE`; rev07 superseded; Truck 2 = `58/60`; O203 partner pickup; `INC-2210` resolved. |
| 11 | `FS-E011-RECALL-NOTICE-RECEIVED` | 09:36 | `EXTERNAL_EVENT` | Regulatory feed | Representative FDA-format notice for LTC-4471 accepted as an external event. | Source event stored; recall chain begins; no later state exposed yet. |
| 12 | `FS-E012-MODEL-ARMOR-PASSED` | 09:36 | `AUTONOMOUS_CHAINED` | Model Armor | Input passes managed safety screening. | Screening evidence stored. A pass is not factual sufficiency and Model Armor is not an agent. |
| 13 | `FS-E013-RECALL-SCOPE-EXTRACTED` | 10:04 | `AUTONOMOUS_CHAINED` | Recall Intake & Extraction | Establishes source-anchored lot and hazard scope without inventing custody. | Validated extraction evidence stored; Activity entry appended. |
| 14 | `FS-E014-RECALL-RESPONSE-SCOPED` | 10:04 | `AUTONOMOUS_CHAINED` | Incident Lead | Selects the governed recall-response playbook and required custody/recovery work. | Recall incident `INC-2231` projected `SCOPING`; agent evidence correlated. |
| 15 | `FS-E015-MOVEMENT-BARRIER-ACTIVATED` | 10:05 | `AUTONOMOUS_CHAINED` | Deterministic safety policy / ledger | Further movement of the affected lot is barred. | Barrier and Site 01 acknowledgment WorkItem become authoritative. No invented human gate. |
| 16 | `FS-E016-CONTAINMENT-IN-PROGRESS` | 10:06 | `AUTONOMOUS_CHAINED` | Private ledger | Recall lifecycle advances after barrier activation. | `INC-2231` = `CONTAINMENT_IN_PROGRESS`. |
| 17 | `FS-E017-REV08-INVALIDATED` | 10:07 | `AUTONOMOUS_CHAINED` | Deterministic policy / ledger | Active plan is no longer safe for the recalled lot. | rev08 becomes `INVALIDATED` in the authoritative projection; no rev09 is invented. |
| 18 | `FS-E018-CUSTODY-RECONCILED` | 10:10 | `AUTONOMOUS_CHAINED` | Network & Custody | Establishes 96 unique, 88 confirmed, and eight unconfirmed at Site 01. | Graph assessment stored; custody nodes remain unchanged; connected graph and exact gap appear. |
| 19 | `FS-E019-SAFE-RECOVERY-PROPOSED` | 10:10 | `AUTONOMOUS_CHAINED` | Fulfillment Planning & Recovery | Selects the safe candidate allocating 18 to Agency 01 and 22 to Agency 02, with Agency 03 short 20. | Advisory recovery proposal validated; no hidden stock invented. |
| 20 | `FS-E020-SAFE-RECOVERY-COMMITTED` | 10:10 | `AUTONOMOUS_CHAINED` | Deterministic policy / ledger | Exactly 40 safe replacements and one 20-case shortfall commit atomically. | Recovery allocations and `SF-A03` stored; projection shows 40/20 truth. |
| 21 | `FS-E021-CLOSURE-REFUSED` | 10:12 | `AUTONOMOUS_CHAINED` | Deterministic closure policy | Eight cases remain unconfirmed, so false containment is refused. | Refusal receipt; zero prohibited domain mutations; governance refusal appended. There is no Closure Judge agent. |
| 22 | `FS-E022-PARTIALLY-CONTAINED` | 10:13 | `AUTONOMOUS_CHAINED` | Private ledger | Terminal canonical Friday state is established. | `INC-2231` = `PARTIALLY_CONTAINED`; canonical custody remains 88/96. |
| 23 | `FS-E023-DAY-OUTCOME-PUBLISHED` | 16:30 | `AUTONOMOUS_SCHEDULED` | Projection | Read-only Friday outcome becomes available. | No mutation: 88/96, 40 recovered, 20 short, Site 01 open. |
| 24 | `FS-E024-SATURDAY-DRAFT-PROPOSED` | 17:00 | `AUTONOMOUS_SCHEDULED` | Fulfillment Planning & Recovery | Selects a feasible next-day candidate under inherited constraints. | Saturday rev01 stored `DRAFT_WITH_CONSTRAINTS`; no activation control. |
| 25 | `FS-E025-OBLIGATIONS-CARRIED-FORWARD` | 17:00 | `AUTONOMOUS_CHAINED` | Deterministic projection | Carries unresolved authoritative Friday truth into Saturday. | Draft shows LTC-4471 barrier, Agency 03 short 20, Site 01 acknowledgment obligation, and unresolved incident. |

## 6. Isolated partner-evidence proof branches

Both branches begin from canonical event 22 and use authenticated callback configuration plus authoritative reads. Neither branch advances or rewrites the canonical cursor.

### 6.1 Vague branch

| Seq | Event ID | Effective time | Actor | Outcome |
| ---: | --- | --- | --- | --- |
| V1 | `FS-PV1-PARTNER-CALLBACK-RECEIVED` | 10:15 | Authenticated partner callback | Source text: “We pulled the remaining lettuce. Should be all good.” |
| V2 | `FS-PV2-MODEL-ARMOR-PASSED` | 10:15 | Model Armor | Text passes safety screening; no factual sufficiency implied. |
| V3 | `FS-PV3-PARTNER-EVIDENCE-PROPOSED` | 10:16 | Partner Operations | Likely intent understood, but lot, quantity, location, and qualifying disposition remain missing or unsupported. |
| V4 | `FS-PV4-PARTNER-EVIDENCE-DENIED` | 10:16 | Deterministic evidence policy / ledger | `DENIED`; domain mutations `0`; evidence mutations `1`; custody `88/96`; WorkItem open; incident unchanged. |

The branch Activity view shows the callback, Partner Operations result, and refusal. Returning to canonical restores event 22 without time travel because the branch never moved the canonical cursor.

### 6.2 Complete branch

| Seq | Event ID | Effective time | Actor | Outcome |
| ---: | --- | --- | --- | --- |
| C1 | `FS-PC1-PARTNER-CALLBACK-RECEIVED` | 10:18 | Authenticated partner callback | Source text: “LTC-4471 · 8 cases · isolated in quarantine at Site 01 · confirmed at 10:18.” |
| C2 | `FS-PC2-MODEL-ARMOR-PASSED` | 10:18 | Model Armor | Text passes safety screening. |
| C3 | `FS-PC3-PARTNER-EVIDENCE-PROPOSED` | 10:19 | Partner Operations | Literal lot, quantity, location, disposition, and confirmation-time claims support the exact open obligation. |
| C4 | `FS-PC4-PARTNER-EVIDENCE-APPLIED` | 10:19 | Deterministic evidence policy / ledger in isolated authority | `APPLIED`; domain mutations `2`; evidence mutations `1`; Site 01 confirmed; acknowledgment WorkItem completed; branch custody `96/96`. |

The complete branch does not change incident status, movement barrier, safe allocations, or Agency 03's shortfall. It does not close the recall. Returning to canonical restores the unchanged 88/96 Friday history.

## 7. Human gates and autoplay

### Required human authority

- Full-system execution includes morning-plan approval at event 3.
- The filmed and public deterministic experience begins at event 5 with morning provenance already committed in read-only history.
- The only interactive human gate in that experience is event 9: exact rev07→rev08 repair approval.
- Autoplay, elapsed wall time, navigation, or keyboard input cannot synthesize approval.

### Controller modes

| Mode | Progression |
| --- | --- |
| `FILM_PRESENTER` | Forward control requests the next permitted event. The controller—not the UI—enforces order. It may pause indefinitely. |
| `JUDGE_AUTOPLAY` | Events advance with compressed, configurable wall-time delays and pause indefinitely at event 9 until approval. |
| `MANAGED_EXECUTION` | Actual accepted external, scheduled, agent, policy, and ledger events determine progression. |

Wall-time animation delay is presentation behavior, not business evidence. Scenario time changes only when the next accepted event commits.

## 8. Replay session contract

A deterministic replay session must:

1. Create a unique opaque session with canonical cursor at event 5.
2. Preload events 1–4 as immutable read-only history.
3. Start, pause, resume, and reset without affecting another session.
4. Advance only through the permitted event graph.
5. Pause at event 9 until one valid synthetic human approval action is accepted.
6. Bind idempotency to session plus action/event identity.
7. Return the original receipt on a duplicate identical action.
8. Deny altered or out-of-order actions without advancing the cursor.
9. Exclude future payloads server-side, including Saturday before event 24.
10. Open vague and complete proof branches without changing the canonical cursor.
11. Return from a proof branch to the same canonical state.
12. Emit only `SYNTHETIC_TEST` evidence and fixture-prefixed run/session/receipt IDs.
13. Avoid Gemini, ADK, Model Armor, KMS, Spanner, or other paid managed calls.
14. Never expose raw partner or recall text over SSE.

Navigation is view selection only. No tab, URL, keyboard shortcut, or page load may request an arbitrary future `as_of` boundary.

## 9. Fleet Activity and frontend projection contract

Fleet Activity is an append-only chronological projection of accepted events, not a static list of five agent cards.

It may show:

- accepted external events;
- what an agent established at a committed evidence boundary;
- human approval events;
- deterministic policy actions and refusals;
- ledger commits and receipts;
- Model Armor as a separate boundary.

It must not show:

- invented `RUNNING`, `WAITING`, duration, tool calls, or ordering;
- future events;
- branch events as canonical history;
- navigation as a business event;
- quiet/nominal text after a failure or incident has committed.

Required experience behavior:

- the persistent operating clock is visible on every surface;
- the refrigeration alarm appears immediately at the top of Today, on Truck 1, and in Fleet Activity;
- the repair proposal and approval control are above the fold at 1600×900;
- incident substates unlock as their events commit;
- changing Incident tabs never changes scenario time;
- Evidence is read-only and contains no mutation-styled approval control;
- Saturday is unavailable before event 24;
- proof branches are clearly labeled `ISOLATED SELECTED PROOF`;
- rev08's route/manifest transformation occurs once after event 10;
- deterministic mode remains disclosed outside film mode.

## 10. Core invariants and acceptance tests

1. No future-state field crosses the replay or projection boundary early.
2. Event sequence is monotonic and gap-free within a session.
3. Navigation never advances or rewinds canonical time.
4. Event 10 cannot occur without event 9's valid receipt.
5. Truck 2 is exactly `58/60` after rev08.
6. Custody reconciles `24 + 22 + 20 + 10 + 8 + 12 = 96` with no double counting.
7. Canonical custody remains `88/96`; complete proof is branch-only `96/96`.
8. Safe recovery is exactly 40 and Agency 03 shortfall is exactly 20.
9. Closure refusal remains deterministic and records zero prohibited domain mutations.
10. Vague partner evidence records one evidence mutation and zero domain mutations.
11. Complete evidence applies exactly two domain mutations and one evidence mutation inside isolated authority.
12. Saturday inherits all four unresolved obligations from canonical Friday state.
13. Reset creates a fresh session at event 5 and cannot alter another session.
14. Two simultaneous judge sessions advance independently.
15. Replay approval succeeds without browser interception.
16. Fleet Activity appends the corresponding event at every boundary and never exposes a later event.

## 11. Implementation firewall

Backend, replay, and frontend implementations may consume this contract but may not silently alter:

- agent ownership defined in Agent Contract V2;
- trigger classification or human gates;
- the canonical numbers, dates, revisions, orders, or incident states;
- partner-proof isolation;
- deterministic closure/refusal authority;
- event ordering or future-state exclusions.

A discovered source limitation must be reported as an implementation delta. It is not permission to rewrite the contract.
