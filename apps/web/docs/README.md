# Full Shelf — React presentation (v4 handoff)

A self-contained **React + TypeScript + Vite** implementation of the Full Shelf v4
fulfillment-control-plane product surfaces. It runs entirely on a **deterministic
synthetic fixture** — there is no live backend, no network calls, no real receipts
or signatures. Every projection reports `dataMode: "SYNTHETIC_TEST"`, which forces the
visible **DETERMINISTIC TEST MODE** banner.

> ⚠️ **Generated, not runtime-verified.** This package was generated in the Claude
> Design environment, which cannot execute a Node/Vite toolchain. It has **not** been
> run through `npm install` / `npm run dev` / `tsc` here. Treat the first local
> `npm run typecheck` + `npm run dev` as the acceptance gate and fix any environment
> nits (dependency versions, minor type strictness) on first run.

## Install & run

```bash
npm install
npm run dev        # Vite dev server → http://localhost:5173
npm run build      # tsc -b + vite build → dist/
npm run preview    # serve the production build
npm run typecheck  # tsc --noEmit (strict)
```

Node 18+ recommended.

## What you get

- **All 12 operational states + History**, reachable from the on-screen state navigator
  (top of the canvas) and from in-product actions (approve, open workspace, section tabs,
  outcome → tomorrow).
- **Loading**, **disconnected** (toggle the connection chip in the top bar), **error**,
  **omitted-field** (`Historical value not retained`), **partial-containment**, and
  **refusal** states.
- The full v4 visual language: daybook header, needs-attention band, Agent Activity rail,
  commitments board, revision review + approval, dispatch schematic (clearly labeled
  *not live GPS*), recall intake, custody graph, governed recovery, governance refusal,
  Today's Outcome, Tomorrow's draft, History ledger, and the Execution Record drawer.

## Project structure

```
full-shelf-react-handoff/
  package.json          # React + ReactDOM + TS + Vite only
  tsconfig.json         # strict
  vite.config.ts
  index.html
  src/
    main.tsx            # ReactDOM root
    App.tsx             # orchestrator: beat state machine, loading/disconnected, view routing
    types/
      fullShelf.ts      # normalized view-model types (the contract)
    data/
      FullShelfDataSource.ts  # the seam interface every source implements
      FixtureDataSource.ts    # deterministic synthetic fixture — the ONLY home of scenario facts
    components/
      TestModeBanner.tsx
      StateNavigator.tsx
      TopBar.tsx
      DaybookHeader.tsx
      AgentActivityRail.tsx
      CommitmentsBoard.tsx
      RevisionReview.tsx
      DispatchSchematic.tsx
      RecallWorkspace.tsx
      IncidentRail.tsx
      CustodyGraph.tsx
      GovernedRecovery.tsx
      GovernanceRefusal.tsx
      TodaysOutcome.tsx
      TomorrowsDraft.tsx
      HistoryLedger.tsx
      ExecutionRecordDrawer.tsx
    styles/
      global.css        # fonts, resets, keyframes, focus, reduced-motion
      tokens.ts         # enum → color/glyph/position maps (styling only, no scenario facts)
      css.ts            # small CSS-string → React style-object helper (memoized)
```

## Architecture rules (enforced by construction)

- **Presentation components hold no authoritative scenario constants.** Every quantity,
  identifier, agency name, lot, revision, and timestamp lives in `FixtureDataSource.ts`.
  Components receive normalized view models and turn enums into styling via `styles/tokens.ts`.
- **One seam.** `App.tsx` depends on `FullShelfDataSource`. Replace
  `createFixtureDataSource()` with a live/replay implementation and no component changes.
- **Truth corrections** from the v4 spec are all applied — see `INTEGRATION_HANDOFF.md`.

See **INTEGRATION_HANDOFF.md** for the surface→component map, the fields a live backend
must supply, and exactly where to add the replay and HTTP adapters.
