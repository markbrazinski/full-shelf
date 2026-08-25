# Frontend Runtime Contract

**Source runtime:** Golden Runtime Controller at SHA
`1ff771e68513055697e2c6db13fa77c6b05e9572`
(tag `golden-runtime-controller-accepted-20260825`)

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
| `current_day.plan_revisions` contains `rev08`, `active_plan_revision: rev08` | cursor 10 |
| `current_day.incidents` contains `INC-2231` | cursor 11 |
| `execution_evidence_as_of.custody_graph` | **cursor 20** (see discrepancy D2) |
| `current_day.recovery` | cursor 20 |
| `carry_forward_obligations` non-empty | cursor 20 (3 entries), 4 entries at cursor 22 |
| incident status `PARTIALLY_CONTAINED` | cursor 22 |
| `next_day_draft` | cursor 24 |

All projection timestamps are canonical Pacific `-07:00` with scenario
wall-clock preserved: `08:05-07:00`, `10:13-07:00`, `17:00-07:00`.

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

## 9. Discrepancies between contract and observed runtime

Reported exactly as found. **No resolution is chosen or invented here.**

### D1 — Repair proposal payload absent at event 8

- **Contract §9** requires: "the repair proposal and approval control are above
  the fold at 1600×900", and §5 event 8 states "Exact rev07→rev08 diff stored as
  `PROPOSED`; approval surface appears above the fold".
- **Observed at cursor 8**
  ([`08-event-proposal-projection.json`](runtime-samples/08-event-proposal-projection.json)):
  `current_day.repair_proposal` is **absent**, `current_day.approvals` is `[]`,
  `dispatch.revision` is still `rev07`, and `commitments` contains only `rev07`
  rows.
- **Consequence:** the only machine-readable description of the proposed diff at
  event 8 is the prose in `activity_entry.detail` of the event-8 envelope
  ("O202 (22 cases) to Truck 2; O203 (20 cases) to refrigerated partner
  pickup"). A frontend cannot render a structured proposal, and cannot construct
  the `plan_diff_hash` approval binding, from the projection at that cursor.
- The `rev08` structure first appears at cursor 10 — *after* approval.

### D2 — Custody graph appears at event 20, not event 18

- **Contract §5** event 18 `FS-E018-CUSTODY-RECONCILED` (10:10) states:
  "Establishes 96 unique, 88 confirmed, and eight unconfirmed at Site 01. Graph
  assessment stored… connected graph and exact gap appear."
- **Observed:** `execution_evidence_as_of.custody_graph` is `null` at cursor 18
  and first carries `96/88/8` at cursor 20.
- **Mechanism:** `session.py` `_fixture_for()` maps cursor 18 to the fixture of
  the most recent fixture-backed event, which is event 15 → `custody.json`; that
  fixture has `custody_graph: null`. The graph lives in `recovery.json`, bound to
  event 20 in `events.py`.
- **Consequence:** a UI that unlocks the custody surface on event 18 renders an
  empty graph for two events.

### D3 — `current_day.vehicles` is `null` until event 22

- **Observed:** `current_day.vehicles` is `null` at cursors 5, 6, 8, and 10, and
  is populated (`TRUCK-02`, 58/60) only from cursor 22.
- **Contract §9** requires the refrigeration alarm to appear "on Truck 1" at
  event 6, and rev08's route/manifest transformation to occur once after event
  10.
- **Consequence:** there is no vehicle record to attach a Truck 1 alarm to at
  event 6, and no `vehicles` entry showing 58/60 at event 10. `dispatch.vehicles`
  is present throughout but its `assigned_cases`, `capacity_cases`, `name`, and
  `is_operational` fields are `null` at cursor 10; only `stops`, `stop_count`,
  and `vehicle_id` are populated. **Truck 1 (`TRUCK-01`) never appears in
  `current_day.vehicles` or `dispatch.vehicles` at any observed cursor.**

### D4 — Contract §9 forbids what the commission asked for

- **Contract §9** forbids showing "invented `RUNNING`, `WAITING`, duration, tool
  calls, or ordering". The runtime honors this: no `RUNNING`, `WAITING`,
  `duration`, or `started_at` appears in any envelope.
- This was recorded as an accepted implementation delta at the runtime's
  acceptance tag. Restated here because it constrains Fleet Activity: agent
  evidence appears **only** at its committed boundary, atomically.

---

## 10. Map inputs

### Available today

| Input | Values observed |
|---|---|
| Custody node IDs | `N-WH` Warehouse, `N-TR2` Truck 2, `N-STG` Pickup Staging, `N-AG01` Agency 01, `N-ST01` Site 01, `N-RESC` Direct Rescue |
| Node types | `WAREHOUSE`, `VEHICLE`, `STAGING`, `AGENCY`, `SUBSITE`, `DIRECT_RESCUE` |
| Node case counts | 24, 22, 20, 10, 8, 12 (sum 96) |
| Node acknowledgment | `CONFIRMED` / `UNCONFIRMED` per node |
| Graph edges | `E-N-TR2`, `E-N-STG`, `E-N-AG01`, … with `source_node_id`, `target_node_id`, `case_count`, `lot_id`, `is_sub_distribution` |
| Agency labels | `Agency 01`–`Agency 05`; recovery uses `AGENCY-01`, `AGENCY-02`, `AGENCY-03` |
| Vehicle ID | `TRUCK-02` (`Refrigerated Truck 2`) |
| Stop sequence | `dispatch.vehicles[].stops[].sequence` 1, 2, 3 with `assignment_type: VEHICLE_ROUTED` |
| Partner pickup | `O203` / `Agency 03` / 20 cases, `assignment_type: PARTNER_PICKUP`, `sequence: null` |
| Sequence basis | `COMMITTED_MANIFEST_ORDER` |

### Missing — explicitly identified

The runtime exposes **no geographic data of any kind**. A grep for
`latitude`, `longitude`, `lat`, `lng`, `coordinates`, and `geo` across all
runtime fixtures returns no positional field. Specifically absent:

1. **Latitude/longitude for every node.** None of `N-WH`, `N-TR2`, `N-STG`,
   `N-AG01`, `N-ST01`, `N-RESC` carries a coordinate.
2. **Street addresses.** No address, city, postal code, or place ID for any
   warehouse, agency, staging point, sub-site, or rescue recipient.
3. **Real East Bay location identity.** Names are generic (`Agency 01`,
   `Site 01`, `Warehouse`). **No actual East Bay place names, addresses, or
   coordinates exist in the accepted runtime.** They cannot be extracted, and
   this packet does not invent them.
4. **Vehicle position.** No current or historical GPS for `TRUCK-01` or
   `TRUCK-02`. ADR-010 records that refrigeration failure is never inferred from
   position, so no position stream exists.
5. **Route geometry.** `stops[].sequence` gives ordering only — no polyline,
   path, distance, or ETA.
6. **Truck 1 record.** `TRUCK-01` appears in `commitments[].vehicle` but never as
   a vehicle object, so it has no capacity, operational flag, or map identity.
7. **Depot/origin geometry.** `recovery.allocations[].source_facility` is `null`
   with `source_facility_basis: "CONFIGURED_TENANT_REFERENCE"` — the reference
   itself is not exposed.

**Any map rendered from this runtime must therefore be schematic** — a custody
graph laid out from `path_depth` and edges, not a geographic map. Producing a
real Google Maps view requires a geocoding input that does not exist at this SHA
and must be supplied as a separate accepted contract.

---

## 11. What this packet does not establish

- It is not independent acceptance of the event or projection contract
  (`AGENTS.md:225`).
- It makes no claim of frontend filmability or production readiness.
- All evidence is `SYNTHETIC_TEST`; nothing here is `OBSERVED_LIVE` or
  `MEASURED`.
- `apps/web` and runtime behavior were not modified in producing it.
