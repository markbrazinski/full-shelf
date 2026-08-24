# ADR 010 — Additive projection delta for the v6.1 control plane

Status: accepted (local; not merged, pushed, or deployed)
Supersedes: nothing. Extends the accepted contract at
`full-shelf-backend-fe-contract-v2`.

## Context

The v6.1 operator control plane needs five facts the projection could not
supply. The supplied design artifact hardcoded all of them, which is exactly
the failure this delta exists to prevent: a polished surface presenting
invented quantities as committed truth.

Each item below was reachable from state the system already commits. Nothing
here adds DDL, a ledger command type, a service, an activation path, or a
claim the backend cannot support.

## Decision

### B1 — Vehicle-failure incident lifecycle

The Friday truck breakdown was committed and receipt-gated, but the projection
knew only the recall containment ladder, so it fell through to `DETECTED` and
never resolved. No surface could derive an incident badge from it without
inferring one from view state.

- `ACTIVE` once the incident's own status receipt commits.
- `RESOLVED` when the approved repair revision commits at or after the
  incident opened, so a pre-incident plan cannot read as its repair.
- Recall incidents keep the containment ladder unchanged.

The authoritative seed spells the event `VEHICLE_FAILURE`; the contract enum
spells it `TRUCK_BREAKDOWN`. Both name one concept, so the projection
recognizes both rather than rewriting committed rows.

Contract: `current_day.incidents[].status` gains `ACTIVE`, `RESOLVED`.

### B2/B4 — Source-backed stop sequence

The map needs numbered stops. The only ordering available was object iteration
order, and the telemetry branch scraped sequence out of rendered display
strings.

The morning-plan seed already held the authority — an ordered `assigned_orders`
manifest per vehicle, corroborated by the breakdown seed (the truck failed
after `AGENCY-01`, first in that manifest). That field was unread. It is now
load-bearing, recorded explicitly as `stop_sequence` on each canonical order.

`sequence_basis: COMMITTED_MANIFEST_ORDER` declares the provenance. This is a
deterministic ordering of committed rows, **not** a routing or optimization
claim: no distance, travel time, or geometry is consulted. A partner pickup
sits on no vehicle manifest and carries a null sequence.

Contract: `current_day.dispatch.sequence_basis`, and `sequence` on both vehicle
stops and partner pickups.

### B3 — Configured source facilities for replacement lots

Recovery names the replacement lot but never said where it is stocked. The
`Lots` table holds no facility column and no hand-off of a replacement case is
recorded anywhere, so this cannot be custody.

`source_facility` is deployment configuration (`LOT_SOURCE_FACILITIES`), in the
same sense as a warehouse address on a printed pick sheet.
`source_facility_basis: CONFIGURED_TENANT_REFERENCE` states that provenance. An
unconfigured tenant projects `null`, never a placeholder — a placeholder would
render as a located fact.

A test pins that configuring a facility adds no custody node or edge: the graph
stays at 96 unique / 88 confirmed / 8 unconfirmed.

Contract: `current_day.recovery.allocations[].source_facility` and
`source_facility_basis`.

### B5 — Persisted candidate next-day schedule

Saturday had committed constraints and unassigned demand but no candidate
assignments. Populating the surface would have meant recomputing values at read
time and presenting them where an operator expects committed state.

Candidate assignments now persist through the existing `CREATE_NEXT_DAY_DRAFT`
command:

- `CreateNextDayDraftPayload` carries `candidate_vehicles` and
  `unassigned_demand`, both optional, so the constraints-only caller contract
  is unchanged.
- A payload validator rejects failed arithmetic before the transaction opens.
- The executor re-validates against authoritative rows **inside** the
  transaction: plan identity, movement barriers, confirmed-safe eligibility,
  vehicle availability and freshness, capacity, per-lot draw, and a matching
  open shortfall. Every failure raises, aborting the transaction, so a rejected
  candidate leaves no partial write.
- Candidate stops persist as child `Orders` of the draft revision. `Orders`
  interleaves in `PlanRevisions`, so a candidate is *structurally* subordinate
  to `DRAFT_WITH_CONSTRAINTS` and cannot outlive it.
- Status is the literal `CANDIDATE`, never an activatable state.
- Unmet demand persists as an `UNASSIGNED_DEMAND` constraint so it stays
  visibly open rather than being absorbed.

The projection **reads** these rows, scoped to the draft's own `plan_id` and
`revision`, and re-derives nothing. `activation_supported` is always `false`.

Order ids derive from the draft plan and the shortfall they serve, so
regeneration is deterministic and idempotency holds.

Contract: `next_day_draft` gains `activation_supported`, `candidate_vehicles`,
`unassigned_demand`, `constraints`.

## Consequences

Additive only. Every change appends to an enum, adds an optional payload field,
or adds a projected field. No existing field changed meaning, and the
constraints-only next-day caller still commits unchanged.

Current-day isolation is enforced by exact plan identity. The fake Spanner in
the projection tests previously ignored `plan_id` on `Orders` reads, which
would have let a Saturday row leak into Friday unnoticed; it now enforces the
predicate production binds, so the isolation tests prove something.

Canonical facts preserved: 96 / 88 / 8 custody, 40 recovered, 20 short, O203
partner pickup, `PARTIALLY_CONTAINED`, `DENIED · 0 MUTATIONS`, and Saturday's
18 + 22 = 40 with Agency 03's 20 cases explicitly unassigned.

## Boundaries deliberately not crossed

No DDL. No new ledger command type. No next-day activation or approval control.
No inbound collections, notification tracking, replacement custody, agent
`RUNNING` states, or real-GPS claims. The five-agent fleet, Model Armor
boundary, deterministic policy, ledger authority, and canonical refusal
behavior are untouched.

## Story delta (approved after B5)

Five further changes, all additive, no DDL:

**Refrigeration failure → proposal → approval.** `VEHICLE_REFRIGERATION_FAILURE`
from `SIMULATED_FLEET_TELEMATICS` is a reported mechanical fault, idempotent on
`source_event_id` via `InboundEvents`'s primary key. It is never inferred from
position: refrigeration status and location are separate signals, and a test
asserts the projection exposes no coordinate, bearing, or speed.

A bounded `PERSIST_REPAIR_PROPOSAL` command persists the resulting proposal as a
constraint on the **source** revision. It writes no `PlanRevisions` row, no
`Orders` row and no `Vehicles` update, so the active plan is untouched and rev07
stays authoritative until approval. It fails closed on an infeasible reroute, a
reroute onto the failed vehicle, an already-existing target revision, or a source
revision that is no longer active — every rejection leaving zero mutations. The
proposal binds the exact diff the approval later signs, hashed with the same
`compute_plan_diff_hash` the KMS envelope uses.

`current_day.repair_proposal` is present only while the revision it repairs is
still active, so an approval control can never appear for work already
committed. `authority` is always `AGENT_PROPOSAL`; `activation_supported` always
false.

**Recall arrival.** `REGULATORY_EVENT_RECEIVED` is the first intake step, making
the authority order explicit: event arrives → Model Armor screens → extraction
reads. `recall_intake_as_of.source` records a representative FDA-format
regulatory notice delivered as an event, with `monitoring_claimed` pinned false.
Full Shelf does not poll or monitor the FDA and the projection must never imply
it does.

**Refusal terminology.** The refusal names what really ran:
`CLOSURE_ELIGIBILITY_CHECK` requested by the coordinator, answered by
`RECORD_REFUSAL` from deterministic policy, `DENIED · 0 MUTATIONS`.
`DECLARE_CONTAINED` is not in the ledger command enum and appears nowhere.

**Custody and recovery hierarchy.** Both surfaces lead with the benefit,
composed from projected quantities only. Human-readable node roles are
presentation metadata; names, quantities, custody states and locations stay
projection-backed.

### Deferred

Inbound food collections are **not** in this slice. Recorded as a post-film
product extension, not a gap in the current story.
