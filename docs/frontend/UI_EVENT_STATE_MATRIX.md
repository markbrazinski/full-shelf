# UI Event State Matrix

**Source runtime:** Golden Runtime Controller after the Frontend Projection
Readiness repair (base accepted runtime
`1ff771e68513055697e2c6db13fa77c6b05e9572`).
Every cell is observed from the running runtime — see
[runtime-samples/](runtime-samples/). Companion document:
[FRONTEND_RUNTIME_CONTRACT.md](FRONTEND_RUNTIME_CONTRACT.md).

Columns follow contract §9's required experience behavior. D1, D2, and D3 from
the previous packet are **resolved** by the readiness repair; D4 (no invented
agent `RUNNING`) stands by design. See
[FRONTEND_RUNTIME_CONTRACT.md §9](FRONTEND_RUNTIME_CONTRACT.md#9-discrepancies--status-after-the-readiness-repair).

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
| 5 | 08:05-07:00 | none | Friday opened | rev07 active; 5 commitments; **both trucks present and AVAILABLE** (TRUCK-01 42 cases, TRUCK-02 36/60); `reference_locations` present; no custody graph | `start` / `advance` | none | CANONICAL | unavailable |
| 6 | 08:20-07:00 | **CRITICAL, action required** | Truck 1 refrigeration failure | rev07 unchanged; `INC-2210` ACTIVE; **TRUCK-01 `alarm.active: true`, `status: REFRIGERATION_FAILURE`, `is_operational: false`**; TRUCK-02 unaffected | `advance` | `INC-2210` opens | CANONICAL | unavailable |
| 7 | 08:20-07:00 | attention | Incident scoped | unchanged; affects O202, O203 | `advance` | `INC-2210` scoped | CANONICAL | unavailable |
| 8 | 08:21-07:00 | **attention, action required** | Repair proposed | rev07 still authoritative, `approvals: []`; **structured `repair_proposal`**: O202 22→TRUCK-02, O203 20→PARTNER_PICKUP, `36 + 22 = 58/60`, `plan_diff_hash`, submit-ready `approval_payload_template` | **`approve` only** — `advance` returns `409 HUMAN_APPROVAL_REQUIRED` | `INC-2210` awaiting approval | CANONICAL | unavailable |
| 9 | 08:24-07:00 | success | Repair approved | still rev07 active; **`repair_proposal.status: APPROVED`** with `approval_receipt_id` populated; receipt on `receipt_refs` | `advance` (autoplay resumes) | `INC-2210` approved | CANONICAL | unavailable |
| 10 | 08:24-07:00 | success | rev08 active | **rev08 active**; O202→TRUCK-02 22; O203 PARTNER_PICKUP 20; `dispatch.revision: rev08`; **TRUCK-02 58/60, `remaining_cases: 2`**; **TRUCK-01 still failed — never silently repaired**; `approvals` populated | `advance` | `INC-2210` resolved | CANONICAL | unavailable |
| 11 | 09:36-07:00 | **CRITICAL, action required** | Recall notice received | `INC-2231` appears, status SCOPING; `recall_intake_as_of` populated | `advance` | `INC-2231` opens | CANONICAL | unavailable |
| 12 | 09:36-07:00 | none | Safety screening passed | unchanged; Model Armor shown as its own boundary, not an agent | `advance` | `INC-2231` scoping | CANONICAL | unavailable |
| 13 | 10:04-07:00 | attention | Recall scope extracted | lot LTC-4471, E. coli O157:H7 | `advance` | `INC-2231` scoping | CANONICAL | unavailable |
| 14 | 10:04-07:00 | attention | Recall response scoped | unchanged | `advance` | `INC-2231` scoping | CANONICAL | unavailable |
| 15 | 10:05-07:00 | **CRITICAL** | Movement barrier active | barrier on LTC-4471; Site 01 acknowledgment WorkItem opens | `advance` | barrier active | CANONICAL | unavailable |
| 16 | 10:06-07:00 | attention | Containment in progress | `INC-2231` → CONTAINMENT_IN_PROGRESS | `advance` | containment | CANONICAL | unavailable |
| 17 | 10:07-07:00 | **CRITICAL** | rev08 invalidated | plan no longer safe for the recalled lot; no rev09 | `advance` | containment | CANONICAL | unavailable |
| 18 | 10:10-07:00 | attention | Custody reconciled | **`custody_graph` present: 96 total / 88 confirmed / 8 unconfirmed**, six nodes and connected edges; 8 unconfirmed at `N-ST01`; no recovery allocations yet | `advance` | custody | CANONICAL | unavailable |
| 19 | 10:10-07:00 | attention | Safe recovery proposed | **`recovery_proposal` advisory**: AGENCY-01 18, AGENCY-02 22, total 40, `SF-A03` 20; `mutation_applied: false`, `commits_at_event: 20`; committed `recovery` still absent | `advance` | recovery | CANONICAL | unavailable |
| 20 | 10:10-07:00 | success | Safe recovery committed | **committed `recovery`** appears: allocations 18+22=40 `COMMITTED`, `SF-A03` 20 OPEN; `carry_forward_obligations` 3 entries | `advance` | recovery committed | CANONICAL | unavailable |
| 21 | 10:12-07:00 | **REFUSAL** | Closure refused | 8 unconfirmed; zero prohibited domain mutations | `advance` | closure refused | CANONICAL | unavailable |
| 22 | 10:13-07:00 | attention | Partially contained | `INC-2231` → **PARTIALLY_CONTAINED**; custody 88/96; TRUCK-02 58/60, TRUCK-01 still failed; `carry_forward_obligations` 4 entries | `advance`, **`branch` now permitted** | terminal canonical | CANONICAL | unavailable |
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

`reference_locations` is present on **every** projection from event 5, canonical
and branch alike, and is byte-identical across sessions and resets.

| Runtime ID | Display name | Lat, Lon | Role | Custody node | Agency / Orders |
|---|---|---|---|---|---|
| `FS-LOC-ACCFB` | Alameda County Community Food Bank | 37.741645, -122.201189 | HUB | `N-WH` | — |
| `FS-LOC-BFN` | Berkeley Food Network | 37.869016, -122.294151 | AGENCY | `N-AG01` | `AGENCY-01` / O201 |
| `FS-LOC-AFB` | Alameda Food Bank | 37.784686, -122.299163 | AGENCY | `N-TR2` | `AGENCY-02` / O202 |
| `FS-LOC-SLCFP` | San Leandro Community Food Pantry | 37.712594, -122.137318 | AGENCY | `N-STG` | `AGENCY-03` / O203 |
| `FS-LOC-PHFS` | Peace Haven Freedom Store | 37.674445, -122.082600 | AGENCY | `N-ST01` | `AGENCY-04` / O204 |
| `FS-LOC-TCV` | Tri-City Volunteers Food Bank | 37.555890, -122.007661 | AGENCY | `N-RESC` | `AGENCY-05` / O205 |

Every entry carries `location_mode: CONFIGURED_REFERENCE` and `live_gps: false`,
and the payload carries the disclosure:

> Configured East Bay reference locations for deterministic demonstration. No
> live GPS or operational affiliation is claimed.

The UI must surface that disclosure wherever the map appears. The named
organizations are real East Bay providers used as plausible geography; no
operational affiliation is claimed, and nothing in this scenario describes
anything they actually did.

**A map can place markers and connect them; it cannot draw a driven route or
show a moving truck.** No route geometry and no live vehicle position exist at
any cursor — `telemetry.position_available` is `false` throughout. See
[FRONTEND_RUNTIME_CONTRACT.md §10](FRONTEND_RUNTIME_CONTRACT.md#10-map-inputs)
for the remaining gaps.
