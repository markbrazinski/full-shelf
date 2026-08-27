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
import { GoldenRuntimeDataSource, type EventEnvelope } from "./data/GoldenRuntimeDataSource";
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
  6: 5_000,   // truck failure
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

    (async () => {
      try {
        const snap = await backend.createSession();
        if (disposed) return;
        sessionId.current = snap.session_id;
        // Acceptance drives the REAL runtime for this session rather than
        // racing autoplay. Exposing the id changes no rendered behavior.
        (window as unknown as { __FS_SESSION_ID?: string }).__FS_SESSION_ID = snap.session_id;
        setCursor(snap.cursor);

        const proj = await backend.getProjection(snap.session_id, snap.cursor);
        if (disposed) return;
        setProjection(proj);
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
            const updated = await backend.getProjection(snap.session_id, seq);
            if (!disposed) setProjection(updated);
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
        if (!disposed && !PRESENTER) setPlaying(true);
      } catch (e) {
        if (!disposed) {
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
        }
      }
    })();

    return () => {
      disposed = true;
      unsubscribe.current?.();
    };
  }, [backend, appendCanonical]);

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

  // ---- frontend-paced autoplay --------------------------------------
  // One committed event per dwell interval. The timer id is held in a ref
  // so ArrowRight (or a pause) can cancel a PENDING tick outright — that
  // is what stops a keypress from appearing to do nothing while an
  // autoplay advance is already in flight.
  const tick = useRef<number | null>(null);

  const cancelTick = useCallback(() => {
    if (tick.current !== null) {
      window.clearTimeout(tick.current);
      tick.current = null;
    }
  }, []);

  useEffect(() => {
    cancelTick();
    if (!playing || paused || branch || !sessionId.current) return;
    // The gate and the two human-held boundaries are not timed: they wait.
    if (gatePaused || cursor === 8) return;
    if (HOLD_EVENTS.has(cursor)) return;
    if (cursor >= 25) return;

    tick.current = window.setTimeout(() => {
      tick.current = null;
      // The runtime remains the authority: it refuses at the gate (409)
      // and this never approves anything on its own.
      backend.advance(sessionId.current).catch(() => {});
    }, dwellFor(cursor));

    return cancelTick;
  }, [playing, paused, branch, cursor, gatePaused, backend, cancelTick]);

  const reconnect = useCallback(async () => {
    if (!sessionId.current) return;
    try {
      setError(null);
      setProjection(await backend.getProjection(sessionId.current, cursor));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [backend, cursor]);

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
        // the cursor already held rather than adopting a new one.
        setProjection(await backend.getProjection(sessionId.current, cursor));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBranchBusy(false);
      }
    },
    [backend, cursor],
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
      setProjection(await backend.getProjection(sessionId.current, cursor));
      // Only now may canonical progression resume, through events 23-25.
      if (!PRESENTER) setPlaying(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBranchBusy(false);
    }
  }, [backend, cursor]);

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
        // Toggle the paced autoplay sequence.
        if (paused) {
          setPaused(false);
          setRecallPaused(false);
          setPlaying(true);
        } else {
          cancelTick();
          setPaused(true);
          setPlaying(false);
        }
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        // Deterministic single step: cancel any pending autoplay tick,
        // stop the sequence, then commit exactly one event. Without the
        // cancel, a tick already in flight could land on top of this
        // keypress and make it look like nothing (or too much) happened.
        cancelTick();
        setPlaying(false);
        setPaused(true);
        // The runtime still refuses at the human gate; this cannot bypass it.
        backend.advance(sessionId.current).catch(() => {});
      } else if (e.code === "KeyR" && e.shiftKey) {
        e.preventDefault();
        // Shift+R, so a stray "r" during a rehearsal cannot wipe the take.
        // Resets only this disposable replay session.
        window.location.reload();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paused, execOpen, backend, cancelTick]);

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
                setPaused(false);
                setRecallPaused(false);
                setPlaying(true);
              } else {
                cancelTick();
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
              if (!sessionId.current) return;
              cancelTick();
              setPlaying(false);
              setPaused(true);
              backend.advance(sessionId.current).catch(() => {});
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
