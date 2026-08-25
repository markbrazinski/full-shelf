# Frontend Runtime Contract

**Source runtime:** Golden Runtime Controller after the Frontend Projection
Readiness repair. Base accepted runtime
`1ff771e68513055697e2c6db13fa77c6b05e9572`
(tag `golden-runtime-controller-accepted-20260825`); samples regenerated from
the repaired runtime.

**Status:** Extraction and documentation. Every value below was observed from the
running accepted runtime and is stored under
[runtime-samples/](runtime-samples/). Nothing here is invented, and no product
interpretation has been applied.

**Authority used, in order:** `AGENTS.md`;
[`docs/strategy/GOLDEN_DEMO_EVENT_CONTRACT.md`](../strategy/GOLDEN_DEMO_EVENT_CONTRACT.md);
[`tools/replay/events.py`](../../tools/replay/events.py);
[`tools/replay/session.py`](../../tools/replay/session.py); observed responses.
Legacy demo-beats, old strategy reports, frontend fixtures, screenshots, and
historical completion reports were **not** used as event authority.

**Evidence classification: `SYNTHETIC_TEST`.** Every response carries
`evidence_classification: "SYNTHETIC_TEST"` and every session, receipt, and
approval identifier is `fixture-`prefixed. This is deterministic replay, not
managed Google execution. `AGENTS.md:225` holds: frontend live wiring waits for
independently accepted event and projection contracts. This packet does not
grant that acceptance.

---

## 1. Transport

Loopback only, default `127.0.0.1:8788`
(`FULL_SHELF_RUNTIME_PORT`). All bodies are JSON.

| Method | Path | Observed status | Sample |
|---|---|---|---|
| `POST` | `/api/v1/replay/sessions` | `201` | [`00-session-created.json`](runtime-samples/00-session-created.json) |
| `GET` | `/api/v1/replay/sessions/{id}` | `200` | [`05-event-opening-state.json`](runtime-samples/05-event-opening-state.json) |
| `GET` | `…/projection` | `200` | [`05-event-opening-projection.json`](runtime-samples/05-event-opening-projection.json) |
| `GET` | `…/stream` | `200` `text/event-stream` | [`SSE-canonical-frames.txt`](runtime-samples/SSE-canonical-frames.txt) |
| `POST` | `…/start` | `200` | — |
| `POST` | `…/pause` | `200` | — |
| `POST` | `…/advance` | `200` / `409` | [`10-…-activation-frame.json`](runtime-samples/10-event-rev08-activation-frame.json), [`08-gate-advance-refused.json`](runtime-samples/08-gate-advance-refused.json) |
| `POST` | `…/approve` | `200` / `409` | [`09-event-approval-accepted.json`](runtime-samples/09-event-approval-accepted.json) |
| `POST` | `…/branch` | `200` / `409` | [`P2-proof-complete-branch.json`](runtime-samples/P2-proof-complete-branch.json) |
| `DELETE` | `…/branch` | `200` | [`P3-canonical-return.json`](runtime-samples/P3-canonical-return.json) |
| `POST` | `…/reset` | `201` | — |
| `GET` | `/api/v1/replay/events` | `200` | [`EVENTS-canonical-table.json`](runtime-samples/EVENTS-canonical-table.json) |

Every response carries `X-Full-Shelf-Replay-Mode: DETERMINISTIC_TEST`. The UI
must disclose deterministic mode outside film mode (contract §9).

## 2. Session lifecycle

A new session returns `cursor: 5` with events 1–5 already in `feed` and events
1–4 in `history` as immutable read-only provenance. Autoplay begins at event 6;
event 5 is never re-emitted.

```
IDLE --start--> PLAYING --(reaches 8)--> PAUSED_HUMAN_GATE
PAUSED_HUMAN_GATE --approve--> PLAYING --(reaches 25)--> COMPLETE
```

Observed `mode` values: `IDLE`, `PLAYING`, `PAUSED`, `PAUSED_HUMAN_GATE`,
`COMPLETE`. `state()` also returns `approval_required`, `approved`, `branch`,
`operating_timestamp`, `classification`, and `synthetic: true`.

## 3. Event envelope

Contract §3 shape, observed verbatim on the wire:

```json
{
  "schema_version": "full-shelf.demo-event.v2",
  "event_id": "FS-E008-REV08-REPAIR-PROPOSED",
  "event_type": "REV08_REPAIR_PROPOSED",
  "scenario_id": "full-shelf-friday-2026-08-14",
  "session_id": "fs-replay-1ec9f81a-…",
  "sequence": 8,
  "effective_at": "2026-08-14T08:21:00-07:00",
  "recorded_at": "2026-08-25T21:55:54.153751+00:00",
  "trigger_class": "AUTONOMOUS_CHAINED",
  "authority": "CANONICAL",
  "actor": {"kind": "AGENT", "id": "full-shelf.fulfillment-planning-recovery.v2"},
  "correlation": {"tenant_id": "east-bay-food-bank", "operating_day": "2026-08-14",
                  "plan_id": "PLAN-2026-08-14", "incident_id": "INC-2210",
                  "source_event_id": null, "agent_run_id": null},
  "source_refs": [], "payload": {},
  "validation": {"status": "ACCEPTED", "reasons": []},
  "receipt_refs": [], "projection_delta": {},
  "activity_entry": {"severity": "ATTENTION", "headline": "Repair proposed",
                     "detail": "O202 (22 cases) to Truck 2; O203 (20 cases) to refrigerated partner pickup. rev07 remains authoritative.",
                     "action_required": true},
  "evidence_classification": "SYNTHETIC_TEST"
}
```

Two fields drive Fleet Activity directly: `activity_entry` (severity, headline,
detail, action_required) and `effective_at` (the operating clock). `severity` is
one of `INFO`, `ATTENTION`, `CRITICAL`, `SUCCESS`, `REFUSAL`.

**`projection_delta` is `{}` on every observed event.** The frontend must re-read
`…/projection` after each frame; the envelope carries no state diff.

**`source_refs` is `[]` on every observed event.** No raw partner or recall
source text crosses SSE (contract §8.14).

## 4. SSE

`GET …/stream`, resume via the `Last-Event-ID` **header**. Ordinals are the
canonical sequence integers.

```
id: 6
event: replay_event
data: {…full envelope…}
```

Observed with `Last-Event-ID: 5`: ids `6 7 8 9 10 … 25`, gap-free, strictly
after the supplied cursor, id 5 never replayed. Events **9 and 10 arrive as
separate frames**. A caught-up stream stays open and emits
`: keep-alive <iso>` comment lines rather than closing.

Malformed cursor → `400 INVALID_LAST_EVENT_ID`.

**Client integration note (observed during capture).** A reader that stops at a
frame boundary while a partial frame is still in its buffer will appear to lose
the final event. Reading byte-accurately recovered all 20 frames including id
25. This is a client parsing concern, not runtime behavior — the runtime emits
25 in both the library and HTTP paths.

## 5. Approval

The single interactive human gate. The complete binding is required:

```json
{
  "plan_id": "PLAN-2026-08-14",
  "incident_id": "INC-2210",
  "expected_revision": "rev07",
  "target_revision": "rev08",
  "actions": [
    {"order_id": "O202", "cases": 22, "disposition": "TRUCK_2"},
    {"order_id": "O203", "cases": 20, "disposition": "PARTNER_PICKUP"}
  ],
  "plan_diff_hash": "<sha256 of canonical JSON of the five fields above>",
  "idempotency_key": "<client key>"
}
```

Observed outcomes:

| Case | Status | Body | Sample |
|---|---|---|---|
| Exact binding | `200` | `events: [9]` only | [`09-event-approval-accepted.json`](runtime-samples/09-event-approval-accepted.json) |
| Identical duplicate | `200` | `duplicate: true`, same `receipt_id` | [`09-approval-duplicate-idempotent.json`](runtime-samples/09-approval-duplicate-idempotent.json) |
| Missing `plan_diff_hash` | `409` | `APPROVAL_BINDING_MISMATCH` | [`09-approval-denied-missing-hash.json`](runtime-samples/09-approval-denied-missing-hash.json) |
| Altered binding | `409` | `APPROVAL_BINDING_MISMATCH` | [`09-approval-denied-altered-binding.json`](runtime-samples/09-approval-denied-altered-binding.json) |
| Advance at gate | `409` | `HUMAN_APPROVAL_REQUIRED` | [`08-gate-advance-refused.json`](runtime-samples/08-gate-advance-refused.json) |

Denial moves no cursor, commits no event, and creates no receipt. **Approval
commits event 9 only** — event 10 is a separate later commit, reached by the
autoplay interval or by the next `/advance`.

The receipt is explicitly synthetic:

```json
{"receipt_id": "fixture-RCT-approval-567445b35677", "synthetic": true,
 "classification": "SYNTHETIC_TEST",
 "disclosure": "Synthetic replay approval. No real authentication, KMS signature, or human identity is claimed."}
```

The UI must not present this as real KMS or human-operator verification.

## 6. Isolated proof branches

`POST …/branch {"proof": "vague"|"complete"}`; `DELETE …/branch` returns.

- **Refused before event 22:** `409 PROOF_BRANCH_NOT_AVAILABLE_YET`
  ([`P0-…json`](runtime-samples/P0-proof-denied-before-event-22.json)).
- **Vague:** `domain_mutations: 0`, `evidence_mutations: 1`, custody stays
  `96/88/8`, final branch event `validation.status: "DENIED"`.
- **Complete:** `domain_mutations: 2`, `evidence_mutations: 1`, branch custody
  `96/96/0`.
- Branch projections carry `authority: "ISOLATED"` and
  `proof_label: "ISOLATED SELECTED PROOF"`; canonical projections carry no
  `authority` key.
- Branch envelopes use a `b`-prefixed ordinal namespace (`b1`…`b4`) that cannot
  collide with canonical SSE ids or `Last-Event-ID`.
- **Canonical return was byte-identical** before and after entering both
  branches, verified by re-read
  ([`P3-canonical-return.json`](runtime-samples/P3-canonical-return.json)
  records `canonical_identical_before_and_after_both_branches: true`).

Canonical custody after return remains **88/96** and the incident remains
`PARTIALLY_CONTAINED`.

## 7. Projection

`GET …/projection` returns the bounded operator projection for the current
cursor, filtered so no field belonging to a later event appears early. Observed
reveal points:

| Field | First observable at |
|---|---|
| `current_day.vehicles` (both trucks) | cursor 5 |
| `reference_locations` | cursor 5 |
| `TRUCK-01.alarm.active: true` | cursor 6 |
| `current_day.repair_proposal` | cursor 8 |
| `repair_proposal.approval_receipt_id` | cursor 9 |
| `active_plan_revision: rev08`, Truck 2 58/60 | cursor 10 |
| `current_day.incidents` contains `INC-2231` | cursor 11 |
| `execution_evidence_as_of.custody_graph` (96/88/8) | cursor 18 |
| `current_day.recovery_proposal` (advisory) | cursor 19 |
| `current_day.recovery` (committed) | cursor 20 |
| incident status `PARTIALLY_CONTAINED` | cursor 22 |
| `next_day_draft` | cursor 24 |

All projection timestamps are canonical Pacific `-07:00` with scenario
wall-clock preserved: `08:05-07:00`, `10:13-07:00`, `17:00-07:00`.

### 7.1 `repair_proposal` — event 8

```json
{
  "proposal_id": "fixture-PROP-rev08",
  "plan_id": "PLAN-2026-08-14", "incident_id": "INC-2210",
  "expected_revision": "rev07", "target_revision": "rev08",
  "status": "PROPOSED",
  "actions": [
    {"order_id": "O202", "agency": "Agency 02", "cases": 22, "lot_id": "LTC-4471",
     "from_vehicle": "TRUCK-01", "to_vehicle": "TRUCK-02", "disposition": "TRUCK_2"},
    {"order_id": "O203", "agency": "Agency 03", "cases": 20, "lot_id": "LTC-4471",
     "from_vehicle": "TRUCK-01", "to_vehicle": null, "disposition": "PARTNER_PICKUP"}
  ],
  "capacity_arithmetic": {
    "vehicle_id": "TRUCK-02", "existing_cases": 36, "added_cases": 22,
    "resulting_cases": 58, "capacity_cases": 60,
    "statement": "36 + 22 = 58/60",
    "both_orders_would_not_fit": "36 + 22 + 20 = 78 exceeds 60"
  },
  "plan_diff_hash": "<canonical sha256>",
  "approval_payload_template": { …binding…, "idempotency_key": null },
  "approval_endpoint": "POST /api/v1/replay/sessions/{session_id}/approve",
  "approval_receipt_id": null
}
```

`approval_payload_template` is submit-ready once the client supplies its own
`idempotency_key`; a test approves using it verbatim. `status` becomes
`APPROVED` and `approval_receipt_id` is populated at event 9.

### 7.2 `vehicles` — from event 5

Both trucks at every cursor. Each entry carries `vehicle_id`, `display_name`,
`refrigeration_capable`, `refrigeration_operational`, `is_operational`,
`status`, `alarm`, `capacity_cases`, `manifest_cases`, `remaining_cases`,
`assigned_orders`, `revision`, and `telemetry`.

| Cursor | TRUCK-01 | TRUCK-02 |
|---|---|---|
| 5 | AVAILABLE, no alarm, 42 cases | AVAILABLE, 36/60 |
| 6+ | `REFRIGERATION_FAILURE`, alarm active, `is_operational: false` | AVAILABLE, 36/60 |
| 10+ | still failed — never silently repaired | 58/60, `remaining_cases: 2`, orders O202/O204/O205 |

`telemetry` is `{live_gps: false, position_available: false, basis:
"SIMULATED_FLEET_TELEMATICS", disclosure: …}` on both trucks at every cursor.

### 7.3 `recovery_proposal` — event 19, advisory only

`{status: "PROPOSED", mutation_applied: false, commits_at_event: 20}` with
allocations `AGENCY-01: 18`, `AGENCY-02: 22`, `total_proposed_cases: 40`, and
shortfall `SF-A03` / `AGENCY-03` / 20. `current_day.recovery` (the committed
allocation, `status: COMMITTED`) does not appear until cursor 20.

## 8. Canonical invariants — verified against live samples

Every one confirmed programmatically from the captured files:

| Invariant | Observed |
|---|---|
| O202: 22 cases → Truck 2 | `rev08` commitment `O202`, `cases: 22`, `vehicle: TRUCK-02` |
| Truck 2 becomes 58/60 | `vehicles[TRUCK-02].assigned_cases: 58`, `capacity: 60`; dispatch stops sum 22+15+21 = 58 |
| O203: 20 → refrigerated partner pickup, not shortfall | `status: PARTNER_PICKUP`, `vehicle: null`, in `dispatch.partner_pickups` |
| Custody 96 / 88 / 8 | `unique_current_cases: 96`, `confirmed_cases: 88`, `unconfirmed_cases: 8`; positions sum 24+22+20+10+8+12 = 96 |
| The 8 unconfirmed are Site 01 | sole `UNCONFIRMED` node is `N-ST01`, `on_hand_cases: 8` |
| Recovery 40 safe replacements | allocations 18 (`AGENCY-01`) + 22 (`AGENCY-02`) = 40, lot `LTC-5090` |
| Agency 03 remains 20 short | `shortfalls[0]`: `SF-A03`, `AGENCY-03`, `cases: 20`, `status: OPEN` |
| Canonical terminal `PARTIALLY_CONTAINED` | `INC-2231.status` at cursor 22 |
| Complete 96/96 proof isolated | branch `96/96/0` under `authority: ISOLATED`; canonical unchanged at 88/96 |
| Saturday carries four obligations | `MOVEMENT_BARRIER` (`BARRIER-4471`), `RECOVERY_SHORTFALL` (`SF-A03`), `ACKNOWLEDGMENT_OBLIGATION` (`WORK-SITE01`), `UNRESOLVED_INCIDENT` (`INC-2231`) |

Saturday draft: `revision: rev01`, `status: DRAFT_WITH_CONSTRAINTS`.

## 9. Discrepancies — status after the readiness repair

D1, D2, and D3 from the previous packet were the subject of the Frontend
Projection Readiness repair and are **resolved**. D4 remains, unchanged and by
design.

### D1 — Structured repair proposal at event 8 — **RESOLVED**

`current_day.repair_proposal` now appears at cursor 8 with `proposal_id`,
`plan_id`, `incident_id`, `expected_revision: rev07`, `target_revision: rev08`,
both actions (O202 22 → `TRUCK_2`, O203 20 → `PARTNER_PICKUP`), the Truck 2
arithmetic, the canonical `plan_diff_hash`, and a complete
`approval_payload_template` missing only the client-generated
`idempotency_key`. A test approves using the template verbatim, proving it
matches the runtime gate exactly. The frontend never parses prose.

Event 8 remains pre-approval rev07 (`active_plan_revision: rev07`,
`approvals: []`, `dispatch.revision: rev07`). Event 9 attaches
`approval_receipt_id` and flips the proposal to `APPROVED`. Event 10 activates
rev08.

### D2 — Custody graph at event 18 — **RESOLVED**

`execution_evidence_as_of.custody_graph` now appears at cursor 18, carrying
96 / 88 / 8 with all six nodes and connected edges. Recovery allocations remain
withheld until cursor 20.

### D3 — Both vehicles from event 5 — **RESOLVED**

`current_day.vehicles` now carries `TRUCK-01` and `TRUCK-02` at every cursor
from 5, each with display name, refrigeration capability and operational state,
capacity, manifest cases, remaining cases, assigned orders, alarm state, and a
simulated-telemetry disclosure. Truck 1 raises its refrigeration alarm exactly
at event 6 and is never silently repaired thereafter. Truck 2 shows 36/60 before
the repair and 58/60 from event 10.

### D4 — Contract §9 forbids invented agent lifecycle — **UNCHANGED, by design**

Contract §9 forbids showing "invented `RUNNING`, `WAITING`, duration, tool
calls, or ordering". The runtime honors this: no such field appears in any
envelope. Fleet Activity therefore shows agent evidence only at its committed
boundary, atomically. This was an accepted implementation delta at the runtime's
acceptance tag and is restated here because it constrains the UI.

---

## 10. Map inputs

### Configured reference locations — **now available**

`reference_locations` appears on every projection, canonical and branch. It is
immutable, identical across sessions and resets, and resolved once at build
time. **The replay runtime performs no geocoding and calls no Google service.**

Envelope fields: `location_mode: CONFIGURED_REFERENCE`, `live_gps: false`,
`geocode_source`, `geocode_source_url`, `geocode_license`,
`geocode_resolved_on`, and the disclosure:

> Configured East Bay reference locations for deterministic demonstration. No
> live GPS or operational affiliation is claimed.

| Runtime ID | Display name | Address | Lat, Lon | Role | Node | Agency / Orders |
|---|---|---|---|---|---|---|
| `FS-LOC-ACCFB` | Alameda County Community Food Bank | 7900 Edgewater Drive, Oakland | 37.741645, -122.201189 | HUB | `N-WH` | — |
| `FS-LOC-BFN` | Berkeley Food Network | 1925 Ninth Street, Berkeley | 37.869016, -122.294151 | AGENCY | `N-AG01` | `AGENCY-01` / O201 |
| `FS-LOC-AFB` | Alameda Food Bank | 677 West Ranger Avenue, Alameda | 37.784686, -122.299163 | AGENCY | `N-TR2` | `AGENCY-02` / O202 |
| `FS-LOC-SLCFP` | San Leandro Community Food Pantry | 14235 Bancroft Avenue, San Leandro | 37.712594, -122.137318 | AGENCY | `N-STG` | `AGENCY-03` / O203 |
| `FS-LOC-PHFS` | Peace Haven Freedom Store | 1063 A Street, Hayward | 37.674445, -122.082600 | AGENCY | `N-ST01` | `AGENCY-04` / O204 |
| `FS-LOC-TCV` | Tri-City Volunteers Food Bank | 37350 Joseph Street, Fremont | 37.555890, -122.007661 | AGENCY | `N-RESC` | `AGENCY-05` / O205 |

**Coordinate provenance.** Resolved 2026-08-25 against OpenStreetMap Nominatim
(© OpenStreetMap contributors, ODbL). Each entry stores its `source_url` and
`osm_place_id` so any reviewer can re-check the value. Each also stores
`match_quality`, recorded honestly rather than rounded up:

| Location | `match_quality` | Meaning |
|---|---|---|
| `FS-LOC-ACCFB`, `FS-LOC-BFN`, `FS-LOC-SLCFP`, `FS-LOC-TCV` | `ORGANIZATION_MATCH` | the geocoder result names the organization itself |
| `FS-LOC-AFB`, `FS-LOC-PHFS` | `ADDRESS_MATCH` | the result resolved the street address, not a named organization record |

All six are inside the Bay Area envelope (lat 37.4–38.1, lon -122.6…-121.9),
asserted by test.

The named organizations are real East Bay food-security providers used as
plausible geography. **No operational affiliation, endorsement, or data-sharing
relationship is claimed or implied**, and no case, order, or incident in this
scenario describes anything those organizations actually did.

### Still missing

1. **Route geometry.** `stops[].sequence` gives ordering only — no polyline,
   path, distance, or ETA. A map can place markers and draw straight lines
   between them; it cannot draw a driven route.
2. **Live vehicle position.** No GPS for either truck at any cursor.
   `telemetry.position_available` is `false` and `live_gps` is `false`
   throughout. ADR-010 records that refrigeration failure is never inferred from
   position, so no position stream exists by design.
3. **Sub-site geography distinct from its parent.** `N-ST01` (Site 01) is
   mapped to `FS-LOC-PHFS`, but the scenario places Site 01 downstream of
   Agency 01; the configured coordinate is a stand-in, not a derived
   parent/child geography.
4. **Depot origin for recovery stock.**
   `recovery.allocations[].source_facility` remains `null` with
   `source_facility_basis: "CONFIGURED_TENANT_REFERENCE"`; the reference itself
   is not exposed.

---

## 11. What this packet does not establish

- It is not independent acceptance of the event or projection contract
  (`AGENTS.md:225`).
- It makes no claim of frontend filmability or production readiness.
- All evidence is `SYNTHETIC_TEST`; nothing here is `OBSERVED_LIVE` or
  `MEASURED`.
- `apps/web` and runtime behavior were not modified in producing it.
