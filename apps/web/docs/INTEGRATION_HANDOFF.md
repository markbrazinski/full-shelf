# Full Shelf v4 → React integration handoff

This document is for the engineer (Claude Code) wiring the audited backend. The
presentation is complete and truthful under a deterministic fixture; your job is to add
real transport behind the existing seam. **No presentation component should need editing.**

---

## 1. v4 surface → React component map

| v4 product surface | Component | Rendered when |
| --- | --- | --- |
| App shell / top bar / Today · History nav | `TopBar` | always |
| DETERMINISTIC TEST MODE banner | `TestModeBanner` | `dataMode === "SYNTHETIC_TEST"` |
| State navigator (12 + History) | `StateNavigator` | always (demo aid) |
| Daybook header (posture, plan revision, obligations, needs-attention) | `DaybookHeader` | `currentDay.inDaybook` |
| Agent Activity rail | `AgentActivityRail` | `projection.agentActivity` present |
| Commitments board + side panels (affected / capacity / approval / recall notice / recent) | `CommitmentsBoard` | `currentDay.commitments` present |
| Revision review + rev07→rev08 diff + human approval | `RevisionReview` | `incident.diffRows` present |
| Dispatch schematic (not live GPS) | `DispatchSchematic` | `projection.dispatch` present |
| Recall intake workspace + Model Armor + invalidation | `RecallWorkspace` | `beat === "recallProcessing"` |
| Incident section rail (E1/E2/E3) | `IncidentRail` | custody/recovery/refusal beats |
| Custody graph + reconciliation (96/88/8) | `CustodyGraph` | `projection.custody` present |
| Governed recovery + authority classes | `GovernedRecovery` | `projection.recovery` present |
| Governance refusal (DENIED · 0 MUTATIONS) | `GovernanceRefusal` | `projection.governance` present |
| Today's Outcome (service vs safety) | `TodaysOutcome` | `projection.outcome` present |
| Tomorrow's constrained draft | `TomorrowsDraft` | `projection.tomorrow` present |
| History ledger (read-only) | `HistoryLedger` | `projection.history` present |
| Execution Record drawer | `ExecutionRecordDrawer` | `evidenceOpen` state |

The 13 beats and their labels/clock times are defined in `data/FixtureDataSource.ts → BEATS`.

## 2. Component → normalized view-model field map

Every component consumes a slice of `FullShelfProjection` (`src/types/fullShelf.ts`):

- `DaybookHeader` ← `currentDay` (`posture`, `authRev`, `authPill`, `openObligations`, `needsAttention`)
- `AgentActivityRail` ← `agentActivity` (`agents[]`, `boundaries[]`, `governanceNote`)
- `CommitmentsBoard` ← `currentDay` (`commitments[]`, `commitmentsSummary`, `affectedPanel`, `capacity`, `approvalRecord`, `recallNoticePanel`, `recentActivity[]`, `obligationsNote`)
- `RevisionReview` ← `incident` (`banner`, `diffRows[]`, `rationale`, `unaffectedNote`, `approvalCta`)
- `DispatchSchematic` ← `dispatch` (`stops`, `vehicles`, `capacityDecision`) — geometry is in the component; **text/values come from the projection**
- `RecallWorkspace` ← `recall` (`intake[]`, `sourceExcerpt`, `sourceAnchoredLot`, `affectedCommitments`, `modelArmor`, `invalidation`)
- `CustodyGraph` ← `custody` (`nodes[]`, `reconciliation[]`, `totalUnique`, `sumExpression`, `caveat`)
- `GovernedRecovery` ← `recovery` (`items[]`, `safeReplacements`, `shortfall`, `authorityNote`)
- `GovernanceRefusal` ← `governance` (`proposal`, `refusal`, `whyCannotClose[]`, `policyNote`)
- `TodaysOutcome` ← `outcome` (`service`, `safety`, `nextRequirements[]`)
- `TomorrowsDraft` ← `tomorrow` (`draftRows[]`, `inheritedObligations[]`, notes)
- `HistoryLedger` ← `history` (`ledger[]`, `lineage[]`, `asOf`, `note`)
- `ExecutionRecordDrawer` ← `executionEvidence` (`coordinator`, `specialists[]`, `modelArmor`, `authority`, `refusal?`)

`styles/tokens.ts` maps enums (`Tone`, `OrderStateTone`, `AgentDisplayStatus`, `AuthorityClass`,
`CustodyStatus`, `Posture`, `Connection`) to colors/glyphs/positions. This is styling only.

## 3. Fields a future backend adapter must provide

The fixture currently supplies these as synthetic values or honest placeholders. A live
adapter must fill them from the audited backend contract:

| Field (projection path) | Current fixture behavior | Live-adapter responsibility |
| --- | --- | --- |
| `executionEvidence.coordinator.status/result` | synthetic | real coordinator run outcome |
| `executionEvidence.specialists[].status/note` | synthetic | real per-specialist completion + result |
| `executionEvidence.specialists[].toolUse` | **only Network & Custody** | real tool-use evidence, **only** where a tool was actually invoked |
| `executionEvidence.authority.ledgerReceiptRef` | `null` → "reference bound in backend" | real ledger receipt reference |
| `executionEvidence.authority.kmsKeyVersion` | `"key version 4"` / `null` | real KMS **key version / verification reference** — never a fabricated signature |
| `executionEvidence.modelArmor.pass` | synthetic PASS after screening | real Model Armor screening response |
| `currentDay.approvalRecord.kmsKeyVersion` | `"key version 4"` | real key version |
| `recall.modelArmor` | `null` until screening completes | real screening result, still gated on completion |
| `recall.affectedCommitments` | `HISTORICAL_NOT_RETAINED` until extracted | real extraction output |
| `asOf` / `currentDay.clock` | fixture times | real as-of timestamp |
| `custody.*`, `recovery.*`, `governance.*` numbers | canonical scenario values | real reconstructed values |

**Never** invent run IDs, session IDs, receipt IDs, signatures, agent timings, or GPS.
Absent data must degrade per §4, not be fabricated.

## 4. Expected omitted / null behavior

- `projection.omittedFields[]` lists fields not yet available for that beat (e.g.
  `"recall.affectedCommitments"`, `"recall.modelArmor"` on `recallReceived`).
- The `HISTORICAL_NOT_RETAINED` sentinel (`"Historical value not retained"`) renders
  literally and must **never** be replaced with a later value.
- `ledgerReceiptRef: null` and `kmsKeyVersion: null` render as "bound in backend" — keep
  this fallback in the live adapter until real references exist.
- `modelArmor: null` → the recall workspace shows `SCREENING…`, not PASS. PASS appears
  **only** once the "Screened" intake step is `COMPLETE`.
- Missing `executionEvidence` → the drawer shows a neutral "no coordinator execution
  recorded for this view" placeholder (see `ExecutionRecordDrawer`).
- Agents only ever use `COMPLETED | NOT_YET_REPORTED | NOT_INVOLVED`. There is no
  Running/Waiting; do not add one.

## 5. Where to add replay and live HTTP adapters

Add two files next to the fixture, each implementing `FullShelfDataSource`:

```
src/data/RecordedReplayDataSource.ts   // RECORDED_LIVE — plays back captured backend events
src/data/LiveHttpDataSource.ts         // OBSERVED_LIVE  — fetches from the real backend
```

Each exports a factory returning `{ getProjection(beatId): Promise<FullShelfProjection> }`
and sets `dataMode` to `"RECORDED_LIVE"` / `"OBSERVED_LIVE"` respectively (which **removes**
the DETERMINISTIC TEST MODE banner automatically — see `TestModeBanner`).

Then change exactly one line in **`src/App.tsx`**:

```ts
// const dataSource = createFixtureDataSource();
const dataSource = createLiveHttpDataSource({ baseUrl: import.meta.env.VITE_API_BASE });
```

The adapter's job is to map backend responses into `FullShelfProjection`. Keep the mapping
inside the adapter; do not leak API-shaped objects into components. This is the intended
seam and the only place transport/auth logic belongs. **Do not** implement a backend client
anywhere else, and do not invent routes — wire the audited contract.

## 6. Visual behavior that depends on synthetic replay mode

- **Loading spinner**: driven by the fixture's ~140 ms artificial latency
  (`createFixtureDataSource({ latencyMs })`). Real adapters get real latency; the spinner
  path is unchanged.
- **Disconnected banner**: currently toggled by the top-bar connection chip (test affordance
  in `App.tsx → toggleConnection`). A live adapter should drive `connectionOverride` /
  `connection` from real transport health instead of the manual toggle.
- **Dispatch schematic** is intentionally static and labeled *not live GPS*. Do not animate
  vehicles or bind positions to live coordinates.
- **Intake `IN_PROGRESS` pulse** is a per-step status style, not a live timer. Drive
  `IntakeStep.status` from real backend events, never from a frontend clock.

## 7. Known limitations

- Generated but **not runtime-verified** in this environment (no `npm`/`tsc`/`vite` run).
  Expect to resolve minor dependency-version or strict-TS nits on first `npm run typecheck`.
- Styling uses a small `css()` string→object helper for fidelity to v4. Hover/focus states
  are handled via `styles/global.css` utility classes and `:focus-visible`; a few bespoke
  v4 hovers are approximated. Swap to CSS Modules / your styling system if preferred — the
  component structure won't change.
- The custody graph and dispatch schematic keep **layout geometry** (node positions, SVG
  paths) in the component; all **labels and numbers** come from the projection. If the
  backend introduces a different set of custody nodes, extend `styles/tokens.ts → CUS_POS`.
- The state navigator is a demo/QA affordance. Hide or remove it for a production shell;
  in-product navigation (approve, open workspace, section tabs, outcome→tomorrow) already
  covers real user paths.
- No routing library is included; beat state is local to `App`. Add your router if deep
  links to states are required.
