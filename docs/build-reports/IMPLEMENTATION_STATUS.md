# Frontend Integration Status — Session-Based Golden Runtime

**Target**: Repoint `apps/web` from beat-driven fixture model to live session-lifecycle API against Golden Runtime Controller (`127.0.0.1:8788`).

**Status**: ✓ Core data layer wired, ✓ typecheck & build pass, ✗ UI/UX fully connected (P1 deferred).

---

## What Works ✓

### Data Layer
- **GoldenRuntimeDataSource** (new): HTTP client for session-lifecycle API on 8788
  - Session create/get
  - Projection fetch
  - SSE subscribe (frame parsing with `Last-Event-ID` header support)
  - Approve binding
  - Start/pause/advance/reset controls
  - Branch enter/exit

- **SessionBridgeDataSource** (new): Adapter preserving beat-based interface, drives real session underneath
  - Minimal wrapper: `getProjection()` returns current session projection
  - `approveRepair()` mapped to session approval binding
  - SSE subscription wired to update subscribers on every committed event
  - **Note**: Autoplay starts on init; event-11 pause policy TBD in UI layer

- **Transport contract** (extended):
  - `RawVehicle` with `alarm` field
  - `RawRecoveryProposal` (advisory, cursor 19)
  - `RawReferenceLocations` (6 East Bay sites, cursor 5+)
  - `RawEventEnvelope` for SSE frames
  - Added to `RawProjection`

- **View model** (extended):
  - `MapLocation[]` for reference_locations
  - `RecoveryProposalView` for advisory state
  - `branchState?: { authority: "ISOLATED"; proofLabel: string }`
  - `cursor?: number` for event tracking

- **SessionNormalizer** (new): Extends old `normalize()` with recovery_proposal, reference_locations, branch state mappings
  - **P1 note**: Reuses old normalizer with hardcoded "healthy" beat ID, does not derive cursor → beat
  - Full rewrite deferred until component gap-fill is complete

- **env.ts** updated:
  - Points to 8788 instead of 8787
  - Returns SessionBridgeDataSource

- **App.tsx** minimal changes:
  - Added `init()` call to SessionBridgeDataSource on mount
  - Everything else preserves existing beat routing (beat → projection → render)

### Verification
- ✓ `npm run typecheck` passes (0 errors)
- ✓ `npm run build` succeeds (vite build 318ms)
- ✓ Runtime server verification:
  - Session creation works
  - Projection endpoint works
  - reference_locations present and correctly shaped (6 locations, not 7)
  - SSE stream ready

---

## What's Deferred (P1 — Critical, for next session)

### UI Layer & Component Integration
1. **Full normalize.ts rewrite** (944 lines)
   - Vehicle mapping (currently stubbed `unknown[]`)
   - Recovery split at cursor 19 vs 20 (currently one type)
   - Full reference_locations mapping
   - Cursor-to-beat derivation
   - **Blocker**: Components still consume old projection shape in most places

2. **GovernedRecovery.tsx split**
   - Must render both `recoveryProposal` (PROPOSED, amber, cursor 19) and `recovery` (COMMITTED, green, cursor 20)
   - Currently only handles `recovery`
   - **Blocker**: Recovery appears on Friday at cursor 20, but proposal should be visible at 19

3. **PartnerEvidenceProof.tsx branch wiring**
   - Must wire actual `onEnterBranch` / `onExitBranch` calls
   - Must show authority and proof label (ISOLATED state)
   - Currently renders content but no interaction (cursor ≥22 only)

4. **Telemetry deletion**
   - Remove `src/data/telemetry/*` (entire directory)
   - Remove `src/components/VehicleTelemetryLayer.tsx`
   - Re-source refrigeration alarm banner from `vehicles[].alarm` field in projection
   - **Impact**: ~40 lines of cleanup, no component changes needed

5. **Old beats/locations cleanup**
   - Delete `src/data/contract/beats.ts` (no longer needed)
   - Delete `src/data/contract/locations.ts` (replaced by runtime's reference_locations)
   - Delete `src/data/FixtureDataSource.ts` (reference only, never active)
   - Delete `src/components/DispatchSchematic.tsx`, `CommitmentsBoard.tsx` (confirmed unused)
   - Update imports

### Visual Design & Parity (P1 for polish)
1. **Design-reference alignment at 1600×900**
   - Dark navy header/nav: ✓ Already correct
   - Light content area: ✓ Already correct
   - Dark Fleet activity rail: Needs verification
   - Map disclosure visible: Needs routing to referenceLocations
   - No telemetry motion: ✓ Will be true after deletion

2. **Saturday unavailability copy**
   - "Next-day planning opens at 17:00" exact phrase TBD in SaturdayCandidatePlan
   - **Note**: Already has `available: false` mechanism, just needs copy

3. **Full-screen testing**: Not done; requires manual walkthrough at 1600×900

### Test Suite
1. **E2E rewrite** (Playwright)
   - Old `views.spec.ts` assumes beat-driven `advance()` with fixed sequence
   - **Needed**: Full session-lifecycle golden path (cursor 5→25, including approval gate at 8)
   - Coverage: event 11 pause, branch enter/exit, reset, mode gating
   - **Est. effort**: 2–3 hours for full coverage

2. **Unit tests for new data layer**
   - GoldenRuntimeDataSource: mock SSE parsing, session CRUD
   - SessionBridgeDataSource: verify event→update propagation
   - SessionNormalizer: verify mappings for recovery_proposal, reference_locations, branch state

---

## Key Risks & Open Questions

1. **Event-11 pause-on-Today policy**: Implemented in SSE handler of SessionBridgeDataSource, but not yet wired to UI
   - Current: autoplay starts on init, pause manually triggers on event 11 if not in Incidents view
   - **Todo**: Wire pause/resume to Incidents nav click

2. **Recovery proposal cursor**: UI_EVENT_STATE_MATRIX shows `recovery_proposal` at cursor 19, `recovery` (committed) at cursor 20
   - SessionNormalizer maps both to the projection
   - **Todo**: Verify old `normalize()` doesn't over-write recovery_proposal with recovery

3. **Idempotency key lifecycle**: Approval binding needs one key per proposal, reused across retries
   - SessionBridgeDataSource generates fresh UUID on each approve call
   - **Todo**: Move to ref in App.tsx, reuse across retries

4. **Branch authority disclosure**: runtime returns `authority: "ISOLATED"` server-side
   - PartnerEvidenceProof needs to display `proof_label: "ISOLATED SELECTED PROOF"` when in branch
   - **Todo**: Wire branchState to component props

---

## How to Continue After This Session

### Priority Sequence (Highest ROI First)

**Phase 1 — Component Gap-Fill** (4–6 hours)
1. Rewrite normalize.ts for vehicle, recovery split, reference_locations, cursor
2. Update GovernedRecovery to render both proposal/committed states
3. Update PartnerEvidenceProof to wire branch enter/exit
4. Delete telemetry, beats, locations files + update imports
5. **Result**: Full data → view model pipeline correct, all components receive right shape

**Phase 2 — Visual Verification** (1–2 hours)
1. Manual walkthrough at 1600×900: header, nav, today/incident/history tabs, Saturday copy
2. Screenshot evidence vs. design-reference
3. Verify no horizontal overflow
4. Check Google Maps script loads (with key) or falls back to SVG

**Phase 3 — E2E Automation** (2–3 hours)
1. Rewrite Playwright spec: one golden-path journey (cursor 5→25)
2. Coverage: approval gate, event-11 pause, branch round-trip, mode gating
3. Headless run against running 8788

**Phase 4 — Polish** (1+ hours if time)
1. Exact copy matching (Saturday 17:00, PARTIALLY_CONTAINED, ISOLATED SELECTED PROOF)
2. Keyboard controls in presenter/debug modes
3. Recovery proposal armor class visibility
4. Custody graph reconciliation sentence

### Estimated Time Budget
- Complete P1 items: ~8 hours
- Full shipping + verification: ~11 hours total (already used ~4 hours on core data layer)
- One working day remains reasonable if focused on sequence above (Phase 1 is the gate)

---

## Commands to Continue

### Local Dev (with running 8788)
```bash
cd apps/web
npm run dev      # Vite on localhost:5173
npm run typecheck  # Verify types
npm run build    # Production bundle
```

### E2E Tests (future)
```bash
npm run e2e      # Playwright (requires 8788 running)
```

### Deploy Artifact
```bash
# After Phase 1 complete, build shipping candidate:
npm run build
# dist/ directory ready for deployment
```

---

## Commit Reference
- `da99fba`: "Frontend integration with Golden Runtime Controller — session-based data layer"
  - Adds GoldenRuntimeDataSource, SessionBridgeDataSource, SessionNormalizer
  - Updates transport/types/env/App for session-lifecycle
  - ✓ Builds, ✓ typechecks, ✓ ready for P1 component gap-fill

---

## Deferred Items (Beyond Scope, Sessions 2+)

- Live orchestrator support (currently hardcoded to 8788 replay only)
- Multi-tenant session isolation (hardcoded single tenant)
- Comprehensive error UI (generic ConnectionError only)
- Performance optimization (SSE re-fetch on every event, no delta optimization)
- Accessibility audit (not performed vs. WCAG)
- Mobile responsive (target 1600×900 only)
