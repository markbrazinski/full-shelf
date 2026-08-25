# UI Event State Matrix

**Source runtime:** Golden Runtime Controller at SHA
`1ff771e68513055697e2c6db13fa77c6b05e9572`.
Every cell is observed from the running accepted runtime — see
[runtime-samples/](runtime-samples/). Companion document:
[FRONTEND_RUNTIME_CONTRACT.md](FRONTEND_RUNTIME_CONTRACT.md).

Columns follow contract §9's required experience behavior. Where the contract
and the observed runtime disagree, the cell states the observation and points at
the discrepancy ID (D1–D4) recorded in the runtime contract. No resolution is
chosen here.

**Reading the columns**

- **Operating time** — `effective_at`, canonical Pacific `-07:00`, visible on
  every surface as the persistent operating clock.
- **Page alert** — top-of-page treatment implied by `activity_entry.severity`
  and `action_required`. `CRITICAL`/`REFUSAL` are alarm-grade.
- **Activity entry** — the verbatim `activity_entry.headline` appended to Fleet
  Activity, which is append-only and chronological.
- **Map / manifest** — what the projection actually carries at that cursor.
- **Action** — the only operator action the runtime accepts.
- **Incident stage** — which incident substates are unlocked.
- **Authority** — `CANONICAL` or `ISOLATED`.
- **Saturday** — presence of `next_day_draft`.

---

## Preloaded history — events 1–4

Delivered in `history` at session creation, before the cursor. Read-only
provenance; not autoplayed and never re-emitted.

| Seq | Time | Activity entry | Severity | Authority |
|---:|---|---|---|---|
| 1 | 05:30 | Morning plan generation triggered | INFO | CANONICAL |
| 2 | 05:30 | rev07 proposed | INFO | CANONICAL |
| 3 | 06:45 | rev07 approved | SUCCESS | CANONICAL |
| 4 | 07:30 | rev07 active | SUCCESS | CANONICAL |

Event 3 is a `HUMAN_GATE` but is **not** interactive: it arrives already
committed. The only interactive gate in the replayed window is event 9.

---

## Canonical timeline — events 5–25

| Seq | Operating time | Page alert | Activity entry | Map / manifest state | Available action | Incident stage | Authority | Saturday |
|---:|---|---|---|---|---|---|---|---|
| 5 | 08:05-07:00 | none | Friday opened | rev07 active; 5 commitments; `dispatch` rev07; **`vehicles: null` (D3)**; no custody graph | `start` / `advance` | none | CANONICAL | unavailable |
| 6 | 08:20-07:00 | **CRITICAL, action required** | Truck 1 refrigeration failure | rev07 unchanged; `INC-2210` ACTIVE; **no Truck 1 vehicle record to alarm on (D3)** | `advance` | `INC-2210` opens | CANONICAL | unavailable |
| 7 | 08:20-07:00 | attention | Incident scoped | unchanged; affects O202, O203 | `advance` | `INC-2210` scoped | CANONICAL | unavailable |
| 8 | 08:21-07:00 | **attention, action required** | Repair proposed | rev07 still authoritative; **`repair_proposal` absent, `approvals: []` (D1)**; diff only as prose in `activity_entry.detail` | **`approve` only** — `advance` returns `409 HUMAN_APPROVAL_REQUIRED` | `INC-2210` awaiting approval | CANONICAL | unavailable |
| 9 | 08:24-07:00 | success | Repair approved | unchanged at this cursor; receipt `fixture-RCT-approval-…` on `receipt_refs` | `advance` (autoplay resumes) | `INC-2210` approved | CANONICAL | unavailable |
| 10 | 08:24-07:00 | success | rev08 active | **rev08 active**; `commitments` gains rev08 rows; O202→TRUCK-02 22; O203 PARTNER_PICKUP 20; `dispatch.revision: rev08`, 3 stops summing 58; `approvals` populated; **`vehicles` still `null` (D3)** | `advance` | `INC-2210` resolved | CANONICAL | unavailable |
| 11 | 09:36-07:00 | **CRITICAL, action required** | Recall notice received | `INC-2231` appears, status SCOPING; `recall_intake_as_of` populated | `advance` | `INC-2231` opens | CANONICAL | unavailable |
| 12 | 09:36-07:00 | none | Safety screening passed | unchanged; Model Armor shown as its own boundary, not an agent | `advance` | `INC-2231` scoping | CANONICAL | unavailable |
| 13 | 10:04-07:00 | attention | Recall scope extracted | lot LTC-4471, E. coli O157:H7 | `advance` | `INC-2231` scoping | CANONICAL | unavailable |
| 14 | 10:04-07:00 | attention | Recall response scoped | unchanged | `advance` | `INC-2231` scoping | CANONICAL | unavailable |
| 15 | 10:05-07:00 | **CRITICAL** | Movement barrier active | barrier on LTC-4471; Site 01 acknowledgment WorkItem opens | `advance` | barrier active | CANONICAL | unavailable |
| 16 | 10:06-07:00 | attention | Containment in progress | `INC-2231` → CONTAINMENT_IN_PROGRESS | `advance` | containment | CANONICAL | unavailable |
| 17 | 10:07-07:00 | **CRITICAL** | rev08 invalidated | plan no longer safe for the recalled lot; no rev09 | `advance` | containment | CANONICAL | unavailable |
| 18 | 10:10-07:00 | attention | Custody reconciled | **`custody_graph` still `null` (D2)** — headline claims 96/88/8 but no graph payload | `advance` | custody | CANONICAL | unavailable |
| 19 | 10:10-07:00 | attention | Safe recovery proposed | advisory only; no recovery payload yet | `advance` | recovery | CANONICAL | unavailable |
| 20 | 10:10-07:00 | success | Safe recovery committed | **`custody_graph` 96/88/8 first appears (D2)**; `recovery` allocations 18+22=40, `SF-A03` 20 OPEN; `carry_forward_obligations` 3 entries | `advance` | recovery committed | CANONICAL | unavailable |
| 21 | 10:12-07:00 | **REFUSAL** | Closure refused | 8 unconfirmed; zero prohibited domain mutations | `advance` | closure refused | CANONICAL | unavailable |
| 22 | 10:13-07:00 | attention | Partially contained | `INC-2231` → **PARTIALLY_CONTAINED**; custody 88/96; `vehicles` populated TRUCK-02 58/60; `carry_forward_obligations` 4 entries | `advance`, **`branch` now permitted** | terminal canonical | CANONICAL | unavailable |
| 23 | 16:30-07:00 | none | Friday outcome published | read-only: 88/96, 40 recovered, 20 short, Site 01 open | `advance` | terminal | CANONICAL | unavailable |
| 24 | 17:00-07:00 | attention | Saturday draft proposed | **`next_day_draft` appears**: rev01, `DRAFT_WITH_CONSTRAINTS`; no activation control | `advance` | terminal | CANONICAL | **available** |
| 25 | 17:00-07:00 | attention | Obligations carried forward | four obligations bound (below) | none — `409 REPLAY_COMPLETE` | terminal | CANONICAL | **available** |

### Event 25 — the four inherited obligations, as observed

| Kind | Reference |
|---|---|
| `MOVEMENT_BARRIER` | `BARRIER-4471` (lot `LTC-4471`) |
| `RECOVERY_SHORTFALL` | `SF-A03` (`INC-2231`) |
| `ACKNOWLEDGMENT_OBLIGATION` | `WORK-SITE01` (`INC-2231`) |
| `UNRESOLVED_INCIDENT` | `INC-2231`, `terminal_state: PARTIALLY_CONTAINED` |

---

## Isolated proof branches

Available **only from event 22**. Before that, `POST …/branch` returns
`409 PROOF_BRANCH_NOT_AVAILABLE_YET`. Entering a branch does not move the
canonical cursor, feed, receipts, or projection.

| State | Operating time | Page alert | Activity entry | Custody shown | Available action | Authority | Saturday |
|---|---|---|---|---|---|---|---|
| Vague branch `b1` | 10:15-07:00 | none | Partner callback received | 88/96 unchanged | `DELETE …/branch` | **ISOLATED** | per canonical cursor |
| Vague `b2` | 10:15-07:00 | none | Safety screening passed | 88/96 | return | ISOLATED | — |
| Vague `b3` | 10:16-07:00 | attention | Partner evidence proposed | 88/96 | return | ISOLATED | — |
| Vague `b4` | 10:16-07:00 | **REFUSAL** | Partner evidence denied | **88/96 unchanged**; 0 domain / 1 evidence mutation; WorkItem stays open | return | ISOLATED | — |
| Complete `c1`–`c2` | 10:18-07:00 | none | Partner callback received / screening passed | 88/96 until applied | return | ISOLATED | — |
| Complete `c3` | 10:19-07:00 | attention | Partner evidence proposed | lot, quantity, location, disposition supported | return | ISOLATED | — |
| Complete `c4` | 10:19-07:00 | success | Partner evidence applied in isolation | **96/96 branch-only**; 2 domain / 1 evidence mutation | return | ISOLATED | — |
| Canonical return | canonical cursor time | none | *(no business event — navigation only)* | **88/96 restored, byte-identical** | canonical actions resume | CANONICAL | per canonical cursor |

Branch projections carry `authority: "ISOLATED"` and
`proof_label: "ISOLATED SELECTED PROOF"`; the UI must label them so. Branch
ordinals are `b`-prefixed and never enter canonical SSE or `Last-Event-ID`.

**Canonical return is not a business event.** Contract §4 classifies it
`NAVIGATION_ONLY`; the runtime emits no envelope for it and the canonical
projection compares byte-identical before and after both branches.

---

## Cross-cutting rules

**Always true**

- Operating clock visible on every surface, canonical Pacific `-07:00`.
- Fleet Activity is append-only and chronological; one entry per committed
  event, never a static list of five agent cards.
- Every response is `SYNTHETIC_TEST`; deterministic mode disclosed outside film
  mode.
- Evidence surfaces are read-only and carry no mutation-styled approval control.
- Changing incident tabs never changes scenario time — tab changes are
  `NAVIGATION_ONLY` and emit no event.

**Never shown**

- Invented `RUNNING`, `WAITING`, duration, tool calls, or agent ordering (D4).
  Agent evidence appears atomically at its committed boundary.
- Any event with `sequence > cursor`.
- Branch events as canonical history.
- Navigation as a business event.
- Quiet or nominal text after a failure or incident has committed.
- Raw partner or recall source text over SSE — `source_refs` is always `[]`.

**Action availability by cursor**

| Cursor | Permitted |
|---|---|
| 5–7 | `start`, `pause`, `advance`, `reset` |
| 8 | `approve` only (`advance` → `409 HUMAN_APPROVAL_REQUIRED`) |
| 9–21 | `start`, `pause`, `advance`, `reset` |
| 22–24 | above, **plus** `branch` / `DELETE branch` |
| 25 | `reset`, `branch` (`advance` → `409 REPLAY_COMPLETE`) |
| any, in branch | `DELETE …/branch` (`advance` → `409 CANONICAL_ADVANCE_BLOCKED_IN_BRANCH`) |

---

## Map surface

The runtime carries **no coordinates, addresses, route geometry, or vehicle
positions** at any cursor. Node identity is symbolic: `N-WH`, `N-TR2`, `N-STG`,
`N-AG01`, `N-ST01`, `N-RESC`, with `node_type`, `on_hand_cases`, `path_depth`,
and typed edges.

Consequently the map surface at every event above is a **schematic custody
graph**, drawn from `path_depth` and edge relationships — not a geographic map.
No real East Bay place names, addresses, or coordinates exist in the accepted
runtime, so none are stated here. See
[FRONTEND_RUNTIME_CONTRACT.md §10](FRONTEND_RUNTIME_CONTRACT.md#10-map-inputs)
for the itemized list of missing map inputs.
