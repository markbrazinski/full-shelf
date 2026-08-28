// =====================================================================
// Full Shelf v7 — Session-Driven Golden Journey
// =====================================================================
// The real session state machine drives everything. Committed events move
// the cursor; navigation selects views only and NEVER advances, rewinds,
// or otherwise mutates scenario time.
//
// Approval is the only visible human mutation gate. Every other surface
// is read-only evidence.
//
// Three modes, and only one of them shows transport:
//
//   default        normal product behavior; autoplay drives the day
//   ?presenter=1   filming: starts PAUSED, keyboard only, NO visible
//                  transport of any kind
//   ?debug=1       visible replay controls, reset, speed, and proof-branch
//                  injection — developer diagnostics only
//
// No keyboard action may bypass the human approval gate, and no mode
// grants authority the product does not already have.
// =====================================================================

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { css } from "./styles/css";
import { plannedStopsFrom } from "./data/contract/plannedStops";
import {
  googleMapsApiKey,
  debugReplayControlsEnabled,
  presenterModeEnabled,
} from "./env";
import { routesForBoundary } from "./data/contract/routeGeometry";
import {
  GoldenRuntimeDataSource,
  type AdvanceResult,
  type EventEnvelope,
} from "./data/GoldenRuntimeDataSource";
import type { FullShelfProjection } from "./types/fullShelf";

import { TodayMapWorkspace } from "./components/TodayMapWorkspace";
import { IncidentWorkspace, type StageKey } from "./components/IncidentWorkspace";
import { HistoryLedger } from "./components/HistoryLedger";
import { ExecutionRecordDrawer } from "./components/ExecutionRecordDrawer";
import { SaturdayCandidatePlan } from "./components/SaturdayCandidatePlan";
import { ConnectionError } from "./components/ConnectionError";
import { RepairProposal } from "./components/RepairProposal";
import { EvidenceBranchPanel, type BranchKind } from "./components/EvidenceBranchPanel";
import { FleetActivityRail, type ActivityRailEntry } from "./components/FleetActivityRail";

const MAPS_API_KEY = googleMapsApiKey();

/**
 * Dead air, in milliseconds, before the first event is allowed to leave.
 *
 * The opening frame is held still so a take can start cleanly: recording
 * begins, the healthy Friday plan is legible, and only then does the day
 * start moving. Presentation only — no cursor moves during the hold.
 */
const OPENING_HOLD_MS = 4_000;

/**
 * The truck-failure sequence, events 6 → 8, is budgeted as ONE beat.
 *
 * Failure, the agent scoping what it broke, and the repair proposal must
 * read as a single continuous reaction, so the three dwells are split
 * from one total rather than tuned individually. Every surface — map,
 * incident banner, and the Fleet activity rail — is driven by the same
 * committed cursor, so budgeting the cursor budgets all of them.
 *
 * Event 8 is not included: it raises the human approval gate and waits
 * indefinitely rather than timing out.
 */
const TRUCK_SEQUENCE_MS = 8_000;

/**
 * Deliberate dwell time, in milliseconds, BEFORE leaving each event.
 *
 * The day is meant to be read, not raced: a viewer must be able to take
 * in what changed before the next commit lands. Pacing is presentation
 * only — it never changes scenario time, which advances solely when the
 * next accepted event commits.
 *
 * Two boundaries hold indefinitely rather than timing out:
 *   11  the recall — held until the operator opens Incidents
 *   24  the Saturday draft — held so the plan can actually be reviewed
 */
const DWELL_MS: Record<number, number> = {
  5: 5_000,   // opening
  // 6 and 7 are apportioned from TRUCK_SEQUENCE_MS, below.
  6: Math.round(TRUCK_SEQUENCE_MS * 0.5),  // truck failure — read the alarm
  7: TRUCK_SEQUENCE_MS - Math.round(TRUCK_SEQUENCE_MS * 0.5),  // scoping → proposal
  10: 5_000,  // rev08 activation
  13: 4_000,  // recall extraction
  14: 4_000,  // scoping
  18: 5_000,  // custody reconciliation
  19: 5_000,  // recovery proposed
  20: 5_000,  // recovery committed
  21: 6_000,  // closure refusal
  22: 6_000,  // partially contained
};
/** Every other committed event. */
const DWELL_DEFAULT_MS = 3_000;
/** Boundaries that wait for a human rather than a timer. */
const HOLD_EVENTS = new Set([11, 24]);

const dwellFor = (cursor: number): number => DWELL_MS[cursor] ?? DWELL_DEFAULT_MS;
const DEBUG_CONTROLS = debugReplayControlsEnabled();
const PRESENTER = presenterModeEnabled();

type View = "today" | "incident" | "history";
type Day = "fri" | "sat";

/** "…T10:13:00-07:00" → "10:13". Never re-derives a date. */
const clockOf = (iso: string): string => /T(\d{2}:\d{2})/.exec(iso)?.[1] ?? iso;

export default function App() {
  const [view, setView] = useState<View>("today");
  const [day, setDay] = useState<Day>("fri");
  // A pinned stage DISPLAYS a completed stage. It never moves the cursor.
  const [pinnedStage, setPinnedStage] = useState<StageKey | null>(null);
  const [projection, setProjection] = useState<FullShelfProjection | null>(null);
  const [cursor, setCursor] = useState(5);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [execOpen, setExecOpen] = useState(false);
  // Canonical activity accumulates across the whole session. Branch
  // activity is held SEPARATELY and belongs to exactly one branch, so a
  // proof's entries can never persist into canonical or leak across into
  // the other proof.
  const [activity, setActivity] = useState<ActivityRailEntry[]>([]);
  const [branchActivity, setBranchActivity] = useState<ActivityRailEntry[]>([]);
  const [gatePaused, setGatePaused] = useState(false);
  // The event-11 presentation hold. It is rendered only while the cursor
  // is still AT event 11: once progression moves on, the banner is stale.
  const [recallPaused, setRecallPaused] = useState(false);
  // Presenter mode opens paused; Space toggles progression.
  const [paused, setPaused] = useState(PRESENTER);
  // Frontend-paced autoplay. `playing` drives the dwell ticker below.
  const [playing, setPlaying] = useState(false);
  const [branch, setBranch] = useState<BranchKind | null>(null);
  const [branchBusy, setBranchBusy] = useState(false);

  const backend = useRef(new GoldenRuntimeDataSource()).current;
  const sessionId = useRef<string>("");
  const unsubscribe = useRef<(() => void) | null>(null);
  const idempotencyKey = useRef<string>("");
  // The view at the moment an event arrives. A ref, not state: the SSE
  // callback closes over its creation scope and would otherwise read a
  // stale view and pause when the operator is already on Incidents.
  const viewRef = useRef<View>("today");
  viewRef.current = view;
  const branchRef = useRef<BranchKind | null>(null);
  branchRef.current = branch;
  // The visible cursor, readable synchronously. `cursor` state is only
  // current as of the last render; a keypress needs the value the
  // operator is looking at right now.
  const cursorRef = useRef(cursor);
  cursorRef.current = cursor;
  /**
   * Live pause state — the authority for "may anything dispatch now?".
   *
   * Deliberately NOT re-synced from `paused` on every render. An
   * unrelated re-render (a committed event moving the cursor, say) can
   * happen between `setPaused(true)` and React processing it, and
   * re-syncing here would resurrect the stale `false` and let an armed
   * timer through. Every transition that changes pause writes this ref
   * first and the state second, so the ref is never behind.
   */
  const pausedRef = useRef(paused);

  /**
   * Monotonic revision for projection writes.
   *
   * The runtime's projection endpoint answers with its state at the
   * moment it is read; it takes no cursor. Two reads issued for two
   * different events can therefore resolve in either order, and the
   * later-issued one is the more current. Each read claims a revision
   * before it is issued, and a resolved read may only be rendered if no
   * newer read has already landed. A stale response is dropped, never
   * rendered.
   */
  const projectionRevision = useRef(0);
  const renderedRevision = useRef(0);

  /** Read the projection and apply it only if nothing newer has landed. */
  const applyProjection = useCallback(
    async (sid: string, observedCursor: number, aborted?: () => boolean): Promise<void> => {
      const revision = ++projectionRevision.current;
      const next = await backend.getProjection(sid, observedCursor);
      if (aborted?.()) return;
      if (revision <= renderedRevision.current) return; // a newer read won
      renderedRevision.current = revision;
      setProjection(next);
    },
    [backend],
  );

  const railEntry = (
    env: EventEnvelope,
    authority: "CANONICAL" | "ISOLATED",
  ): ActivityRailEntry => ({
    ordinal: String(env.sequence),
    clock: clockOf(env.effective_at),
    severity: env.activity_entry?.severity ?? "INFO",
    headline: env.activity_entry?.headline ?? env.event_type,
    detail: env.activity_entry?.detail ?? "",
    actionRequired: env.activity_entry?.action_required === true,
    authority,
  });

  const appendCanonical = useCallback((env: EventEnvelope) => {
    const entry = railEntry(env, "CANONICAL");
    // Append-only and chronological, de-duplicated by ordinal so an SSE
    // resume can never double-post a committed event.
    setActivity((prev) =>
      prev.some((e) => e.ordinal === entry.ordinal) ? prev : [...prev, entry],
    );
  }, []);

  // ---- session bootstrap --------------------------------------------
  useEffect(() => {
    let disposed = false;
    let openingHold: number | null = null;

    (async () => {
      try {
        const snap = await backend.createSession();
        if (disposed) return;
        sessionId.current = snap.session_id;
        // Acceptance drives the REAL runtime for this session rather than
        // racing autoplay. Exposing the id changes no rendered behavior.
        (window as unknown as { __FS_SESSION_ID?: string }).__FS_SESSION_ID = snap.session_id;
        setCursor(snap.cursor);

        await applyProjection(snap.session_id, snap.cursor, () => disposed);
        if (disposed) return;
        setLoading(false);

        // Subscribe BEFORE autoplay so no committed frame is missed.
        unsubscribe.current = backend.subscribe(
          snap.session_id,
          undefined,
          async (env) => {
            if (disposed) return;
            const seq = typeof env.sequence === "number" ? env.sequence : Number(env.sequence);

            // Branch ordinals are `b`-prefixed and never canonical history.
            if (!Number.isFinite(seq)) return;

            // A canonical frame still in flight when a proof opens must
            // not land: inside an isolated authority the rail shows
            // canonical history only up to the cursor the branch was
            // entered at, and the cursor itself must not move.
            if (branchRef.current) return;

            appendCanonical(env);
            setCursor(seq);

            // Event 11 — the recall arrives. If the operator is still on
            // Today, progression HOLDS until they open Incidents. This is
            // a presentation pause: it moves no cursor and mutates nothing.
            if (seq === 11 && viewRef.current === "today") {
              await backend.pause(snap.session_id).catch(() => {});
              if (!disposed) setRecallPaused(true);
            }

            // Event 8 raises the human approval gate.
            if (seq === 8 && !disposed) setGatePaused(true);
            if (seq === 9 && !disposed) setGatePaused(false);

            // The envelope carries no state diff (`projection_delta` is
            // always {}), so the projection is re-read on every frame.
            // Never while inside a branch: that would overwrite isolated
            // state with canonical.
            if (branchRef.current) return;
            // Revision-guarded: two frames read concurrently may resolve
            // in either order, and only the newer read may render.
            await applyProjection(snap.session_id, seq, () => disposed || branchRef.current !== null);
          },
          (err) => {
            if (!disposed) setError(err instanceof Error ? err.message : String(err));
          },
        );

        // Pacing is driven HERE, one committed event per dwell interval,
        // rather than by the runtime's fixed-interval loop — that is what
        // lets each event hold for as long as it needs to be read, and
        // lets ArrowRight cancel a pending tick deterministically.
        // Presenter mode is a filming surface and starts PAUSED.
        //
        // The first tick is held for OPENING_HOLD_MS so the page opens on
        // a still frame. The hold arms no timer of its own beyond this
        // one: `setPlaying` is what schedules the first dwell, so nothing
        // can advance before it fires. A presenter keypress during the
        // hold still works — ArrowRight is a manual step and does not
        // depend on `playing`.
        if (!disposed && !PRESENTER) {
          openingHold = window.setTimeout(() => {
            if (!disposed) setPlaying(true);
          }, OPENING_HOLD_MS);
        }
      } catch (e) {
        if (!disposed) {
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
        }
      }
    })();

    return () => {
      disposed = true;
      if (openingHold !== null) window.clearTimeout(openingHold);
      unsubscribe.current?.();
    };
  }, [backend, appendCanonical, applyProjection]);

  // ---- clicking Incidents releases the event-11 hold -----------------
  // In PRESENTER mode opening Incidents changes the view and nothing
  // else: progression stays exactly where the presenter left it, so a
  // take is never disturbed by a navigation click.
  useEffect(() => {
    if (!recallPaused || view !== "incident" || !sessionId.current) return;
    if (PRESENTER || paused) {
      setRecallPaused(false);
      return;
    }
    setRecallPaused(false);
    setPlaying(true);
  }, [view, recallPaused, paused]);

  // ---- the single-flight transition controller -----------------------
  // EVERY frontend advancement path goes through here, and nothing else
  // may call `backend.advance` directly: the autoplay timer, ArrowRight,
  // the debug step, and Space, whose resume re-arms the timer chain
  // rather than dispatching. The approval continuation needs no client
  // advance at all — approving commits event 9 in the runtime and the
  // frame arrives over SSE — so the gate stays runtime-enforced and no
  // path here can approve anything on its own.
  //
  // Two invariants, and the whole controller exists for them:
  //
  //   1. At most ONE `/advance` is ever in flight. A second caller does
  //      not dispatch: it joins the request already running and reads
  //      what that request committed. That is what makes ArrowRight
  //      during an in-flight autoplay advance commit exactly one event
  //      instead of two.
  //
  //   2. Every scheduled timer carries the generation it was armed in.
  //      Pausing, stepping, or dispatching bumps the generation, so a
  //      timer whose callback is already queued finds itself stale and
  //      dispatches nothing. Cancelling a timeout alone cannot do this:
  //      a fired-but-not-yet-run callback is past cancellation.
  const tick = useRef<number | null>(null);
  /** Bumped by anything that invalidates scheduled work. */
  const generation = useRef(0);
  /** The `/advance` currently in flight, shared by every joining caller. */
  const inFlight = useRef<Promise<AdvanceResult> | null>(null);

  /**
   * Invalidate all scheduled work.
   *
   * Clears a pending timeout AND bumps the generation, so a timer that
   * has already fired — whose callback is sitting on the task queue and
   * can no longer be cleared — still refuses to dispatch when it runs.
   */
  const cancelTick = useCallback(() => {
    generation.current += 1;
    if (tick.current !== null) {
      window.clearTimeout(tick.current);
      tick.current = null;
    }
  }, []);

  /**
   * Dispatch one `/advance`, or join the one already in flight.
   *
   * Returns the runtime's own result, so a caller can tell whether the
   * cursor actually moved. Refusals (409 at the human gate, in-branch,
   * replay complete) resolve rather than throw: they are legitimate
   * runtime answers, not transport failures.
   */
  const requestAdvance = useCallback((options?: { manual?: boolean }): Promise<AdvanceResult> => {
    if (!sessionId.current) return Promise.resolve({ ok: false });
    // The pause is enforced HERE, at the one place a request can be
    // opened, not only where timers are scheduled. `paused` is state, so
    // the autoplay effect that unschedules a timer cannot run until the
    // next render; on a starved main thread an already-armed timer can
    // fire before that render happens. A manual step is the operator
    // asking to move while paused, and is the one permitted exception.
    if (pausedRef.current && !options?.manual) return Promise.resolve({ ok: false });
    // Single flight. A concurrent caller shares this exact promise and
    // never opens a second request.
    if (inFlight.current) return inFlight.current;

    const run = backend
      .advance(sessionId.current)
      .catch((): AdvanceResult => ({ ok: false }))
      .finally(() => {
        inFlight.current = null;
      });
    inFlight.current = run;
    return run;
  }, [backend]);

  /**
   * Serializes manual steps behind one another.
   *
   * Requirement pull in two directions, and this is the seam between
   * them. A keypress may CONSUME an autoplay advance already in flight —
   * the operator asked to move on by one, and the timer is delivering
   * exactly that. A keypress may NOT consume another keypress's advance:
   * three presses are three deliberate steps and must commit three
   * events. Chaining each step onto the previous one keeps both true
   * without ever putting two requests on the wire at once.
   */
  const stepChain = useRef<Promise<unknown>>(Promise.resolve());
  /** The in-flight autoplay advance a queued step has already claimed. */
  const pendingClaim = useRef<Promise<AdvanceResult> | null>(null);

  // ---- frontend-paced autoplay --------------------------------------
  // One committed event per dwell interval, armed against the generation
  // live when it was scheduled.
  useEffect(() => {
    cancelTick();
    if (!playing || paused || branch || !sessionId.current) return;
    // The gate and the two human-held boundaries are not timed: they wait.
    if (gatePaused || cursor === 8) return;
    if (HOLD_EVENTS.has(cursor)) return;
    if (cursor >= 25) return;

    const armed = generation.current;
    tick.current = window.setTimeout(() => {
      tick.current = null;
      // A pause or a keypress that landed after this timer fired has
      // already moved the generation on. A stale timer commits nothing.
      if (generation.current !== armed) return;
      // The runtime remains the authority: it refuses at the gate (409)
      // and this never approves anything on its own.
      void requestAdvance();
    }, dwellFor(cursor));

    return cancelTick;
  }, [playing, paused, branch, cursor, gatePaused, cancelTick, requestAdvance]);

  /**
   * The manual single step, shared by ArrowRight and the debug control.
   *
   * Order matters. It cancels scheduled autoplay and pauses FIRST, so
   * nothing new can be armed while it works. It records the cursor the
   * operator can actually see, then — if an autoplay advance is already
   * in flight — waits for that request instead of racing it. If that
   * request moved the cursor, the operator's step is already satisfied
   * and no second event is committed. Otherwise exactly one advance is
   * dispatched. Either way the session remains paused afterwards.
   */
  const stepOnce = useCallback((): Promise<void> => {
    if (!sessionId.current) return Promise.resolve();
    // Pause synchronously, before this step queues, so a timer can never
    // arm behind a press that is still waiting its turn. The ref is the
    // dispatch authority and is set here rather than by each caller.
    cancelTick();
    pausedRef.current = true;
    setPlaying(false);
    setPaused(true);

    // An advance in flight RIGHT NOW belongs to the autoplay timer, and
    // exactly one step may consume it. Claimed here, at press time,
    // rather than inside the queued body: by the time the body runs, an
    // earlier press may already have started a request of its own, which
    // this press must never mistake for the timer's.
    const consumable = pendingClaim.current === null ? inFlight.current : null;
    if (consumable) pendingClaim.current = consumable;

    const step = stepChain.current.then(async () => {
      const from = cursorRef.current;
      if (consumable) {
        const settled = await consumable;
        if (pendingClaim.current === consumable) pendingClaim.current = null;
        // The autoplay request already delivered this operator's step.
        if (settled.ok && settled.sequence !== undefined && settled.sequence > from) return;
      }
      await requestAdvance({ manual: true });
    });

    // A failed step must not wedge the chain for every later press.
    stepChain.current = step.catch(() => {});
    return step;
  }, [cancelTick, requestAdvance]);

  const reconnect = useCallback(async () => {
    if (!sessionId.current) return;
    try {
      setError(null);
      await applyProjection(sessionId.current, cursor);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [cursor, applyProjection]);

  // ---- the only human mutation gate ---------------------------------
  const approveRepair = useCallback(async () => {
    const template = projection?.repairProposal?.approvalPayloadTemplate;
    if (!sessionId.current || !template) throw new Error("No submit-ready proposal");

    if (!idempotencyKey.current) idempotencyKey.current = crypto.randomUUID();

    // The runtime's own binding, verbatim. Only the idempotency key is
    // ours; altering any bound value invalidates the approval.
    await backend.approve(sessionId.current, {
      ...template,
      idempotency_key: idempotencyKey.current,
    });
    // Event 9 arrives over SSE and re-reads the projection.
  }, [projection, backend]);

  // ---- isolated proof branches --------------------------------------
  const enterBranch = useCallback(
    async (kind: BranchKind) => {
      if (!sessionId.current) return;
      setBranchBusy(true);
      try {
        // Canonical progression PAUSES for the duration of a proof.
        // Without this, autoplay keeps committing events 23-25 while the
        // operator is inside an isolated authority, so the rail would
        // show canonical state the branch view must not imply.
        await backend.pause(sessionId.current).catch(() => {});

        const result = await backend.enterBranch(sessionId.current, kind);
        setBranch(kind);
        branchRef.current = kind;

        // REPLACE, never append. Both proofs number their events b1..b4,
        // so accumulating would let the vague branch's entries surface
        // inside the complete branch under a colliding ordinal.
        setBranchActivity(result.events.map((env) => railEntry(env, "ISOLATED")));

        // Entering a proof must not move the canonical cursor: re-read at
        // the cursor already held rather than adopting a new one. The
        // revision guard makes this read win over any canonical read
        // still in flight when the proof opened.
        await applyProjection(sessionId.current, cursor);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBranchBusy(false);
      }
    },
    [backend, cursor, applyProjection],
  );

  const exitBranch = useCallback(async () => {
    if (!sessionId.current) return;
    setBranchBusy(true);
    try {
      await backend.exitBranch(sessionId.current);
      setBranch(null);
      branchRef.current = null;
      // A proof leaves no trace: every isolated entry is removed.
      setBranchActivity([]);
      // Canonical returns byte-identical: 88/96 and PARTIALLY_CONTAINED.
      await applyProjection(sessionId.current, cursor);
      // Only now may canonical progression resume, through events 23-25.
      if (!PRESENTER) setPlaying(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBranchBusy(false);
    }
  }, [backend, cursor, applyProjection]);

  // ---- presenter keyboard (no visible transport in film mode) -------
  // Shortcuts are ignored while focus is in an input or inside a dialog
  // or drawer, and NOTHING here can bypass the human approval gate: the
  // runtime refuses `advance` at event 8 with 409, and this handler has
  // no approval path of its own.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!sessionId.current) return;
      const t = e.target as HTMLElement | null;
      if (t?.closest("input, textarea, select, [contenteditable='true']")) return;
      // A drawer or modal owns the keyboard while it is open.
      if (t?.closest("[role='dialog']")) return;
      if (execOpen) return;

      if (e.code === "Space") {
        e.preventDefault();
        // Toggle the paced autoplay sequence. The live value is read from
        // a ref, not the render closure: two Space presses inside one
        // render would otherwise both see the same stale `paused` and
        // resolve to the same direction instead of toggling.
        if (pausedRef.current) {
          pausedRef.current = false;
          setPaused(false);
          setRecallPaused(false);
          // Resuming arms exactly one timer chain: the autoplay effect
          // cancels whatever was scheduled before scheduling again, so a
          // repeated resume cannot stack a second chain.
          setPlaying(true);
        } else {
          // Pausing invalidates scheduled work, including a timer that
          // has already fired and is waiting to run.
          cancelTick();
          pausedRef.current = true;
          setPaused(true);
          setPlaying(false);
        }
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        // The shared single-flight step. It cancels scheduled autoplay,
        // pauses, joins any advance already in flight rather than racing
        // it, and commits exactly one event in total.
        // The runtime still refuses at the human gate; this cannot bypass it.
        void stepOnce();
      } else if (e.code === "KeyR" && e.shiftKey) {
        e.preventDefault();
        // Shift+R, so a stray "r" during a rehearsal cannot wipe the take.
        // Resets only this disposable replay session.
        window.location.reload();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [execOpen, cancelTick, stepOnce]);

  const p = projection;
  const activeIncidents = p?.incidentSummary.activeCount ?? 0;
  // Delivered work from a superseded revision stays on the map: the
  // delivery happened, and a plan change does not undo it.
  const deliveredCommitments = useMemo(
    () => (p?.currentDay.commitments ?? []).filter((c) => c.stateTone === "delivered"),
    [p?.currentDay.commitments],
  );
  const plannedStops = useMemo(
    () => (p?.dispatch ? plannedStopsFrom(p.dispatch, deliveredCommitments) : []),
    [p?.dispatch, deliveredCommitments],
  );
  // Which routes apply is decided by committed state: the vehicle alarm
  // the runtime reports, and the active plan revision it publishes.
  const truck1Failed = !!p?.fleet?.some((v) => v.alarm.active);
  const rev08Active = p?.currentDay.authRev === "rev08";
  const routes = useMemo(
    () => routesForBoundary({ truck1Failed, rev08Active }),
    [truck1Failed, rev08Active],
  );
  const locations = p?.referenceLocations ?? [];

  // Saturday opens only once the runtime supplies `next_day_draft` (24).
  const saturdayAvailable = !!p?.tomorrow?.available;
  useEffect(() => {
    if (day === "sat" && !saturdayAvailable) setDay("fri");
  }, [day, saturdayAvailable]);

  // Branches are refused by the runtime before the canonical terminal
  // state. Read that from the projection, never from a local counter.
  const branchAvailable =
    p?.incidentSummary.incidents.some((i) => i.status === "PARTIALLY_CONTAINED") ?? false;

  const branchCustody = p?.custody
    ? { total: p.custody.totalUnique, confirmed: p.custody.confirmed, unconfirmed: p.custody.unconfirmed }
    : null;

  if (error) {
    return (
      <div style={css("height:100vh;display:flex;flex-direction:column;background:#eef0ea")}>
        <ConnectionError detail={error} onReconnect={reconnect} />
      </div>
    );
  }

  return (
    <div
      data-testid="app-root"
      data-cursor={String(cursor)}
      data-branch={branch ?? "canonical"}
      style={css("height:100vh;display:flex;flex-direction:column;background:#eef0ea;overflow:hidden")}
    >
      {/* HEADER */}
      <header
        style={css(
          "flex:none;height:50px;background:#16323b;color:#eef4f4;display:flex;align-items:center;" +
            "justify-content:space-between;padding:0 18px;gap:18px;z-index:8",
        )}
      >
        <div style={css("display:flex;align-items:baseline;gap:9px;min-width:0")}>
          <span style={css("font-size:15px;font-weight:600;letter-spacing:-.01em")}>Full Shelf</span>
          <span className="mono" style={css("font-size:9.5px;letter-spacing:.14em;color:#7e939c;white-space:nowrap")}>
            FULFILLMENT CONTROL PLANE
          </span>
        </div>

        <div style={css("display:flex;align-items:center;gap:10px;min-width:0")}>
          <span
            className="mono"
            style={css(
              "font-size:10.5px;color:#aebfc4;background:#1f3d47;border:1px solid #2b4c56;border-radius:5px;padding:4px 9px;white-space:nowrap",
            )}
            data-testid="auth-rev"
          >
            {p?.currentDay.authRev ?? "—"}
          </span>
          {branch ? (
            <span
              className="mono"
              data-testid="header-branch-label"
              style={css(
                "font-size:9.5px;font-weight:700;letter-spacing:.06em;color:#d9cff0;background:#3b2f5c;" +
                  "border:1px solid #5b4b8a;border-radius:5px;padding:4px 9px;white-space:nowrap",
              )}
            >
              ◆ {p?.branchState?.proofLabel ?? "ISOLATED SELECTED PROOF"}
            </span>
          ) : null}
        </div>

        <div style={css("display:flex;align-items:center;gap:10px")}>
          <div style={css("text-align:right;line-height:1.2")}>
            <div className="mono" style={css("font-size:11.5px;font-weight:600")} data-testid="clock">
              {p?.currentDay.clock ?? "—"}
            </div>
            <div className="mono" style={css("font-size:9.5px;color:#8ea1a7;white-space:nowrap")}>
              {p?.currentDay.operatingDate ?? ""}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setExecOpen(true)}
            data-testid="open-execution-record"
            style={css(
              "background:#1f3d47;color:#cfe0e4;border:1px solid #2b4c56;border-radius:6px;padding:6px 11px;" +
                "font-size:11.5px;font-weight:600;cursor:pointer;white-space:nowrap",
            )}
          >
            Execution record
          </button>
        </div>
      </header>

      <div style={css("flex:1;display:flex;min-height:0")}>
        {/* LEFT NAV — selects views only. Never touches the cursor. */}
        <nav
          aria-label="Primary"
          style={css(
            "flex:none;width:186px;background:#12292f;color:#a9bcc2;display:flex;flex-direction:column;padding:12px 10px;gap:3px",
          )}
        >
          {(
            [
              ["today", "Today", "▦"],
              ["incident", "Incidents", "◆"],
              ["history", "History", "◷"],
            ] as [View, string, string][]
          ).map(([id, label, icon]) => {
            const active = view === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setView(id)}
                aria-current={active ? "true" : "false"}
                data-testid={`nav-${id}`}
                style={css(
                  `display:flex;align-items:center;gap:10px;background:${active ? "#1f3d47" : "transparent"};` +
                    `color:${active ? "#eef4f4" : "#a9bcc2"};border:none;border-radius:8px;padding:10px 12px;` +
                    "cursor:pointer;text-align:left;font-size:13px;font-weight:600",
                )}
              >
                <span
                  className="mono"
                  style={css(`font-size:13px;width:16px;text-align:center;color:${active ? "#8fc6da" : "#5e7982"}`)}
                >
                  {icon}
                </span>
                <span style={css("flex:1")}>{label}</span>
                {id === "incident" && activeIncidents > 0 ? (
                  <span
                    className="mono"
                    data-testid="incident-badge"
                    style={css(
                      `font-size:10px;font-weight:700;background:${active ? "#c14a34" : "#3a2320"};` +
                        "color:#f0d0c8;border-radius:10px;min-width:18px;text-align:center;padding:2px 6px",
                    )}
                  >
                    {activeIncidents}
                  </span>
                ) : null}
              </button>
            );
          })}
        </nav>

        {/* WORKSPACE */}
        <main
          style={css(
            "flex:1;min-width:0;display:flex;flex-direction:column;background:#eef0ea;overflow:auto;padding:14px 20px 16px;gap:12px",
          )}
        >
          {loading ? (
            <div style={css("flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:15px")}>
              <span
                className="fs-spin"
                style={css("width:30px;height:30px;border-radius:50%;border:3px solid #d3dad7;border-top-color:#1f6f8b")}
              />
              <div className="mono" style={css("font-size:12px;letter-spacing:.1em;color:#74848a")}>
                Loading control plane…
              </div>
            </div>
          ) : null}

          {!loading && p ? (
            view === "today" ? (
              <TodayView
                p={p}
                day={day}
                setDay={setDay}
                saturdayAvailable={saturdayAvailable}
                recallPaused={recallPaused && cursor === 11}
                onOpenIncidents={() => setView("incident")}
                plannedStops={plannedStops}
                routes={routes}
                locations={locations}
              />
            ) : view === "incident" ? (
              activeIncidents > 0 || p.recall ? (
                <>
                  <IncidentWorkspace
                    p={p}
                    cursor={cursor}
                    pinnedStage={pinnedStage}
                    onPinStage={setPinnedStage}
                    onOpenEvidence={() => setExecOpen(true)}
                    branchResolved={!!branch && branchCustody?.unconfirmed === 0}
                  />
                  {/* Proof branches are DEBUG-ONLY. In product and
                      presenter modes no selection control renders; a
                      branch injected by debug still shows its received
                      partner response and stays isolated. */}
                  {DEBUG_CONTROLS || branch ? (
                    <EvidenceBranchPanel
                      available={branchAvailable}
                      active={branch}
                      busy={branchBusy}
                      proofLabel={p.branchState?.proofLabel ?? null}
                      evidence={p.partnerEvidence?.[0]}
                      custody={branchCustody}
                      showControls={DEBUG_CONTROLS}
                      onEnter={enterBranch}
                      onExit={exitBranch}
                    />
                  ) : null}
                </>
              ) : (
                <Empty
                  text="No incident is open at this boundary."
                  testId="incident-none"
                />
              )
            ) : (
              <HistoryLedger
                history={p.history ?? { asOf: "", ledger: [], lineage: [], note: "" }}
                onToday={() => setView("today")}
              />
            )
          ) : null}
        </main>

        {/* SIDECAR — approval gate above the chronological activity rail */}
        {!loading && p ? (
          <aside
            style={css(
              // 360px is 22.5% of the 1600px acceptance viewport, so the
              // rail stays supporting evidence rather than the subject.
              "flex:none;width:360px;background:#16323b;color:#eef4f4;display:flex;flex-direction:column;" +
                "overflow:hidden;border-left:1px solid #0f1f23",
            )}
          >
            {p.repairProposal && p.repairProposal.status !== "APPROVED" ? (
              <div style={css("flex:none;padding:12px;border-bottom:1px solid #1e3a42;overflow:auto;max-height:52%")}>
                <RepairProposal
                  proposal={p.repairProposal}
                  alarm={
                    gatePaused
                      ? {
                          vehicleId: p.repairProposal.failedVehicleId,
                          receivedAt: p.currentDay.clock,
                          source: "fleet telematics",
                        }
                      : undefined
                  }
                  onApprove={approveRepair}
                />
              </div>
            ) : null}
            {/* Canonical events, plus the CURRENT branch's entries only. */}
            <FleetActivityRail
              entries={branch ? [...activity, ...branchActivity] : activity}
              onOpenReceipt={() => setExecOpen(true)}
            />
          </aside>
        ) : null}
      </div>

      {/* DEBUG ONLY. Absent from the product and from the filmed frame. */}
      {DEBUG_CONTROLS ? (
        <div
          data-testid="replay-controls"
          style={css(
            "flex:none;background:#0b1a20;border-top:1px solid #1e3a42;color:#cfe0e4;display:flex;" +
              "align-items:center;gap:12px;padding:8px 18px",
          )}
        >
          <span className="mono" style={css("font-size:9px;letter-spacing:.1em;color:#7e939c;font-weight:700")}>
            DEBUG · REPLAY
          </span>
          <button
            type="button"
            data-testid="debug-play"
            onClick={() => {
              if (!sessionId.current) return;
              if (paused) {
                pausedRef.current = false;
                setPaused(false);
                setRecallPaused(false);
                setPlaying(true);
              } else {
                cancelTick();
                pausedRef.current = true;
                setPaused(true);
                setPlaying(false);
              }
            }}
            style={css(
              "background:#1f3d47;border:1px solid #2b4c56;color:#cfe0e4;border-radius:6px;" +
                "padding:6px 12px;font-size:11.5px;font-weight:700;cursor:pointer",
            )}
          >
            {paused ? "Play" : "Pause"}
          </button>
          <button
            type="button"
            data-testid="debug-advance"
            onClick={() => {
              // The same single-flight step the keyboard uses. A debug
              // control may not open a second advancement path.
              void stepOnce();
            }}
            style={css(
              "background:#1f3d47;border:1px solid #2b4c56;color:#cfe0e4;border-radius:6px;" +
                "padding:6px 12px;font-size:11.5px;font-weight:600;cursor:pointer",
            )}
          >
            Advance →
          </button>
          <button
            type="button"
            data-testid="debug-reset"
            onClick={() => window.location.reload()}
            style={css(
              "background:#1f3d47;border:1px solid #2b4c56;color:#cfe0e4;border-radius:6px;" +
                "padding:6px 12px;font-size:11.5px;font-weight:500;cursor:pointer",
            )}
          >
            Reset
          </button>
          <span className="mono" data-testid="debug-cursor" style={css("font-size:10px;color:#9fb4ba;margin-left:auto")}>
            EVENT {cursor} / 25
          </span>
        </div>
      ) : null}

      {execOpen ? (
        <ExecutionRecordDrawer evidence={p?.executionEvidence} onClose={() => setExecOpen(false)} />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------

function TodayView({
  p,
  day,
  setDay,
  saturdayAvailable,
  recallPaused,
  onOpenIncidents,
  plannedStops,
  routes,
  locations,
}: {
  p: FullShelfProjection;
  day: Day;
  setDay: (d: Day) => void;
  saturdayAvailable: boolean;
  recallPaused: boolean;
  onOpenIncidents: () => void;
  plannedStops: ReturnType<typeof plannedStopsFrom>;
  routes: ReturnType<typeof routesForBoundary>;
  locations: NonNullable<FullShelfProjection["referenceLocations"]>;
}) {
  // The alarm is a reported mechanical fault carried on the vehicle
  // itself, raised at event 6. It is NOT derived from the proposal — the
  // failure is visible before any repair is proposed.
  //
  // The PAGE-LEVEL alert belongs to the unresolved incident, not to the
  // vehicle: once the runtime reports INC-2210 RESOLVED (rev08 committed)
  // the red banner goes, while Truck 1 stays truthfully unavailable in
  // the fleet inventory below. The truck is still broken; the incident is
  // no longer outstanding work.
  const alarmedVehicle = p.fleet?.find((v) => v.alarm.active);
  const alarmIncidentOpen = p.incidentSummary.incidents.some(
    (i) => i.id === alarmedVehicle?.alarm.incidentId && i.active,
  );
  const alarmed = alarmIncidentOpen ? alarmedVehicle : undefined;

  return (
    <>
      {/* Event 6 — the refrigeration failure, prominent and unmissable. */}
      {alarmed ? (
        <div
          data-testid="truck-failure-alert"
          style={css(
            "flex:none;background:#f3e5e1;border:1px solid #e3c3ba;border-left:5px solid #a23b2b;" +
              "border-radius:10px;padding:13px 18px;display:flex;align-items:center;gap:14px;flex-wrap:wrap",
          )}
        >
          <span className="mono" style={css("font-size:20px;color:#a23b2b;flex:none")}>■</span>
          <div style={css("flex:1;min-width:260px")}>
            <div className="mono" style={css("font-size:10px;letter-spacing:.09em;color:#8a2f22;font-weight:700")}>
              CRITICAL · {alarmed.vehicleId} {(alarmed.alarm.kind ?? "FAULT").replace(/_/g, " ")}
              {alarmed.alarm.incidentId ? ` · ${alarmed.alarm.incidentId}` : ""}
            </div>
            <div style={css("font-size:14.5px;font-weight:600;color:#8a2f22;margin-top:3px")}>
              {alarmed.displayName} — cold-chain capability unavailable; refrigerated commitments
              require recovery
            </div>
            <div className="mono" style={css("font-size:9.5px;color:#9a4a3a;margin-top:4px")}>
              reported mechanical fault
              {alarmed.alarm.raisedAtEvent ? ` · raised at event ${alarmed.alarm.raisedAtEvent}` : ""}
            </div>
          </div>
        </div>
      ) : null}

      {/* Event 11 — the recall holds progression while still on Today. */}
      {recallPaused ? (
        <div
          data-testid="recall-pause-banner"
          style={css(
            "flex:none;background:#f3e5e1;border:1px solid #e3c3ba;border-left:5px solid #a23b2b;border-radius:10px;" +
              "padding:13px 18px;display:flex;align-items:center;gap:14px;flex-wrap:wrap",
          )}
        >
          <span className="mono" style={css("font-size:20px;color:#a23b2b;flex:none")}>■</span>
          <div style={css("flex:1;min-width:240px")}>
            <div className="mono" style={css("font-size:10px;letter-spacing:.09em;color:#8a2f22;font-weight:700")}>
              CRITICAL · RECALL NOTICE RECEIVED
            </div>
            <div style={css("font-size:14.5px;font-weight:600;color:#8a2f22;margin-top:3px")}>
              A food-safety recall is waiting. Open Incidents to work it.
            </div>
          </div>
          <button
            type="button"
            data-testid="open-incidents-cta"
            onClick={onOpenIncidents}
            style={css(
              "background:#a23b2b;color:#fff;border:none;border-radius:7px;padding:9px 17px;" +
                "font-size:12.5px;font-weight:600;cursor:pointer;flex:none",
            )}
          >
            Open Incidents
          </button>
        </div>
      ) : null}

      <div style={css("flex:none;display:flex;align-items:center;justify-content:space-between;gap:16px")}>
        <div style={css("display:flex;background:#e2e6df;border-radius:9px;padding:3px")}>
          <button
            type="button"
            onClick={() => setDay("fri")}
            aria-pressed={day === "fri"}
            data-testid="day-fri"
            style={css(
              `background:${day === "fri" ? "#16323b" : "transparent"};color:${day === "fri" ? "#eef4f4" : "#5c6b71"};` +
                "border:none;border-radius:7px;padding:6px 13px;font-size:12px;font-weight:600;cursor:pointer",
            )}
          >
            Friday · Operating
          </button>
          <button
            type="button"
            onClick={() => saturdayAvailable && setDay("sat")}
            aria-pressed={day === "sat"}
            disabled={!saturdayAvailable}
            data-testid="day-sat"
            data-available={String(saturdayAvailable)}
            title={saturdayAvailable ? undefined : "Next-day planning opens at 17:00"}
            style={css(
              `background:${day === "sat" ? "#16323b" : "transparent"};` +
                `color:${day === "sat" ? "#eef4f4" : saturdayAvailable ? "#5c6b71" : "#a3adb0"};` +
                "border:none;border-radius:7px;padding:6px 13px;font-size:12px;font-weight:600;" +
                `cursor:${saturdayAvailable ? "pointer" : "not-allowed"}`,
            )}
          >
            Saturday · Draft
          </button>
        </div>

        {saturdayAvailable && day === "fri" ? (
          <button
            type="button"
            data-testid="saturday-ready-cta"
            onClick={() => setDay("sat")}
            style={css(
              "display:flex;align-items:center;gap:8px;background:#fbf3e2;border:1px solid #e6cf9e;" +
                "color:#7a4f10;border-radius:8px;padding:7px 13px;font-size:12.5px;font-weight:700;cursor:pointer",
            )}
          >
            <span style={css("width:8px;height:8px;border-radius:50%;background:#c98a2e")} />
            Saturday draft ready — Review plan →
          </button>
        ) : null}
      </div>

      {day === "sat" && p.tomorrow ? (
        <SaturdayCandidatePlan
          view={p.tomorrow}
          locations={locations}
          mapsApiKey={MAPS_API_KEY}
        />
      ) : (
        <TodayMapWorkspace
          currentDay={p.currentDay}
          dispatch={
            p.dispatch ?? {
              title: "",
              schematicLabel: "",
              note: "",
              stops: {},
              vehicles: {},
              capacityDecision: {
                beforeLabel: "", beforeValue: "", addLabel: "", addValue: "",
                afterLabel: "", afterValue: "", afterFillPct: 0, remainingLabel: "",
                remainingValue: "", needsLabel: "", needsValue: "", verdict: "", explain: "",
              },
            }
          }
          fleet={p.fleet}
          mapsApiKey={MAPS_API_KEY}
          plannedStops={plannedStops}
          routes={routes}
          locations={locations}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------

function Empty({ text, testId }: { text: string; testId: string }) {
  return (
    <div
      data-testid={testId}
      style={css(
        "background:#fff;border:1px dashed #d5d8d2;border-radius:10px;padding:28px;" +
          "text-align:center;font-size:12.5px;color:#74848a;line-height:1.6",
      )}
    >
      {text}
    </div>
  );
}
