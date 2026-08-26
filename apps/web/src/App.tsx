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
// Presenter transport controls are deliberately absent from the film
// canvas. Hidden keyboard shortcuts remain for a presenter (space / →/ R).
// =====================================================================

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { css } from "./styles/css";
import { plannedStopsFrom } from "./data/contract/plannedStops";
import { googleMapsApiKey } from "./env";
import { GoldenRuntimeDataSource, type EventEnvelope } from "./data/GoldenRuntimeDataSource";
import type { FullShelfProjection } from "./types/fullShelf";

import { TestModeBanner } from "./components/TestModeBanner";
import { TodayMapWorkspace } from "./components/TodayMapWorkspace";
import { RecallWorkspace } from "./components/RecallWorkspace";
import { HistoryLedger } from "./components/HistoryLedger";
import { ExecutionRecordDrawer } from "./components/ExecutionRecordDrawer";
import { SaturdayCandidatePlan } from "./components/SaturdayCandidatePlan";
import { ConnectionError } from "./components/ConnectionError";
import { RepairProposal } from "./components/RepairProposal";
import { CustodyGraph } from "./components/CustodyGraph";
import { GovernanceRefusal } from "./components/GovernanceRefusal";
import { RecoveryProposed, RecoveryCommitted } from "./components/ServiceRecovery";
import { EvidenceBranchPanel, type BranchKind } from "./components/EvidenceBranchPanel";
import { FleetActivityRail, type ActivityRailEntry } from "./components/FleetActivityRail";

const MAPS_API_KEY = googleMapsApiKey();
const AUTOPLAY_MS = 900;

type View = "today" | "incident" | "history";
type Day = "fri" | "sat";
type IncidentTab = "intake" | "custody" | "recovery" | "evidence";

/** "…T10:13:00-07:00" → "10:13". Never re-derives a date. */
const clockOf = (iso: string): string => /T(\d{2}:\d{2})/.exec(iso)?.[1] ?? iso;

export default function App() {
  const [view, setView] = useState<View>("today");
  const [day, setDay] = useState<Day>("fri");
  const [incidentTab, setIncidentTab] = useState<IncidentTab>("intake");
  const [projection, setProjection] = useState<FullShelfProjection | null>(null);
  const [cursor, setCursor] = useState(5);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [execOpen, setExecOpen] = useState(false);
  const [activity, setActivity] = useState<ActivityRailEntry[]>([]);
  const [gatePaused, setGatePaused] = useState(false);
  const [recallPaused, setRecallPaused] = useState(false);
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

  const appendActivity = useCallback((env: EventEnvelope, authority: "CANONICAL" | "ISOLATED") => {
    const entry: ActivityRailEntry = {
      ordinal: String(env.sequence),
      clock: clockOf(env.effective_at),
      severity: env.activity_entry?.severity ?? "INFO",
      headline: env.activity_entry?.headline ?? env.event_type,
      detail: env.activity_entry?.detail ?? "",
      actionRequired: env.activity_entry?.action_required === true,
      authority,
    };
    // Append-only and chronological, de-duplicated by ordinal so an SSE
    // resume can never double-post a committed event.
    setActivity((prev) =>
      prev.some((e) => e.authority === authority && e.ordinal === entry.ordinal)
        ? prev
        : [...prev, entry],
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

            appendActivity(env, "CANONICAL");
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

        await backend.start(snap.session_id, AUTOPLAY_MS);
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
  }, [backend, appendActivity]);

  // ---- clicking Incidents releases the event-11 hold -----------------
  useEffect(() => {
    if (!recallPaused || view !== "incident" || !sessionId.current) return;
    (async () => {
      await backend.start(sessionId.current, AUTOPLAY_MS).catch(() => {});
      setRecallPaused(false);
    })();
  }, [view, recallPaused, backend]);

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
        const result = await backend.enterBranch(sessionId.current, kind);
        setBranch(kind);
        branchRef.current = kind;
        for (const env of result.events) appendActivity(env, "ISOLATED");
        setProjection(await backend.getProjection(sessionId.current, cursor));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBranchBusy(false);
      }
    },
    [backend, cursor, appendActivity],
  );

  const exitBranch = useCallback(async () => {
    if (!sessionId.current) return;
    setBranchBusy(true);
    try {
      await backend.exitBranch(sessionId.current);
      setBranch(null);
      branchRef.current = null;
      // Canonical returns byte-identical: 88/96 and PARTIALLY_CONTAINED.
      setProjection(await backend.getProjection(sessionId.current, cursor));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBranchBusy(false);
    }
  }, [backend, cursor]);

  // ---- hidden presenter keys (no visible transport in film mode) -----
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!sessionId.current) return;
      const t = e.target as HTMLElement | null;
      if (t?.matches("input, textarea, select, [contenteditable='true']")) return;

      if (e.code === "Space") {
        e.preventDefault();
        if (recallPaused) {
          backend.start(sessionId.current, AUTOPLAY_MS).catch(() => {});
          setRecallPaused(false);
        } else {
          backend.pause(sessionId.current).catch(() => {});
          setRecallPaused(true);
        }
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        backend.advance(sessionId.current).catch(() => {});
      } else if (e.code === "KeyR") {
        e.preventDefault();
        window.location.reload();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recallPaused, backend]);

  const p = projection;
  const activeIncidents = p?.incidentSummary.activeCount ?? 0;
  const plannedStops = useMemo(() => (p?.dispatch ? plannedStopsFrom(p.dispatch) : []), [p?.dispatch]);
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
      <TestModeBanner dataMode={p?.dataMode ?? "SYNTHETIC_TEST"} />

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
                recallPaused={recallPaused}
                onOpenIncidents={() => setView("incident")}
                plannedStops={plannedStops}
                locations={locations}
              />
            ) : view === "incident" ? (
              <IncidentView
                p={p}
                tab={incidentTab}
                setTab={setIncidentTab}
                branch={branch}
                branchBusy={branchBusy}
                branchAvailable={branchAvailable}
                branchCustody={branchCustody}
                onEnterBranch={enterBranch}
                onExitBranch={exitBranch}
                onOpenEvidence={() => setExecOpen(true)}
              />
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
              "flex:none;width:376px;background:#16323b;color:#eef4f4;display:flex;flex-direction:column;" +
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
            <FleetActivityRail entries={activity} />
          </aside>
        ) : null}
      </div>

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
  locations,
}: {
  p: FullShelfProjection;
  day: Day;
  setDay: (d: Day) => void;
  saturdayAvailable: boolean;
  recallPaused: boolean;
  onOpenIncidents: () => void;
  plannedStops: ReturnType<typeof plannedStopsFrom>;
  locations: NonNullable<FullShelfProjection["referenceLocations"]>;
}) {
  // The alarm is a reported mechanical fault carried on the vehicle
  // itself, raised at event 6. It is NOT derived from the proposal — the
  // failure is visible before any repair is proposed — and never from a
  // position, of which none exists.
  const alarmed = p.fleet?.find((v) => v.alarm.active);

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
              {" "}· not derived from position
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
      </div>

      {day === "sat" && p.tomorrow ? (
        <SaturdayCandidatePlan view={p.tomorrow} locations={locations} />
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
          mapsApiKey={MAPS_API_KEY}
          plannedStops={plannedStops}
          locations={locations}
          locationDisclosure={p.locationDisclosure}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------

const INCIDENT_TABS: [IncidentTab, string][] = [
  ["intake", "Intake"],
  ["custody", "Custody"],
  ["recovery", "Recovery"],
  ["evidence", "Selected proof"],
];

function IncidentView({
  p,
  tab,
  setTab,
  branch,
  branchBusy,
  branchAvailable,
  branchCustody,
  onEnterBranch,
  onExitBranch,
  onOpenEvidence,
}: {
  p: FullShelfProjection;
  tab: IncidentTab;
  setTab: (t: IncidentTab) => void;
  branch: BranchKind | null;
  branchBusy: boolean;
  branchAvailable: boolean;
  branchCustody: { total: number; confirmed: number; unconfirmed: number } | null;
  onEnterBranch: (k: BranchKind) => void;
  onExitBranch: () => void;
  onOpenEvidence: () => void;
}) {
  const recallIncident = p.incidentSummary.incidents.find((i) => i.type === "FOOD_SAFETY_RECALL");

  return (
    <>
      <div style={css("flex:none;display:flex;align-items:center;gap:12px;flex-wrap:wrap")}>
        <div className="mono" style={css("font-size:11px;color:#74848a;letter-spacing:.02em")}>
          {recallIncident?.id ?? "Incidents"} · {recallIncident?.affectedLotId ?? "—"}
        </div>
        {recallIncident ? (
          <span
            className="mono"
            data-testid="incident-status"
            style={css(
              "font-size:9.5px;font-weight:700;letter-spacing:.06em;color:#8a5a12;background:#f8eedc;" +
                "border:1px solid #ead3a9;border-radius:5px;padding:4px 9px",
            )}
          >
            {recallIncident.status}
          </span>
        ) : null}

        {/* Tabs select views only — NAVIGATION_ONLY, no cursor change. */}
        <div style={css("display:flex;background:#e2e6df;border-radius:9px;padding:3px;margin-left:auto")}>
          {INCIDENT_TABS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              aria-pressed={tab === id}
              data-testid={`incident-tab-${id}`}
              style={css(
                `background:${tab === id ? "#16323b" : "transparent"};color:${tab === id ? "#eef4f4" : "#5c6b71"};` +
                  "border:none;border-radius:7px;padding:6px 13px;font-size:12px;font-weight:600;cursor:pointer",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "intake" ? (
        p.recall ? (
          <RecallWorkspace
            recall={p.recall}
            source={p.recallSource}
            onToday={() => setTab("custody")}
            onGo={() => setTab("custody")}
            onOpenEvidence={onOpenEvidence}
          />
        ) : (
          <Empty text="No recall intake has been committed at this boundary." testId="incident-intake-empty" />
        )
      ) : null}

      {tab === "custody" ? (
        p.custody ? (
          <CustodyGraph custody={p.custody} onOpenEvidence={onOpenEvidence} />
        ) : (
          <Empty text="Custody reconciliation has not been committed at this boundary." testId="incident-custody-empty" />
        )
      ) : null}

      {tab === "recovery" ? (
        <div style={css("display:flex;flex-direction:column;gap:14px")}>
          {/* Event 19 advisory and event 20 committed are genuinely
              different states. The committed allocation replaces the
              advisory one; it never merely relabels it. */}
          {p.recovery ? (
            <RecoveryCommitted recovery={p.recovery} />
          ) : p.recoveryProposal ? (
            <RecoveryProposed proposal={p.recoveryProposal} />
          ) : (
            <Empty text="No recovery has been proposed at this boundary." testId="incident-recovery-empty" />
          )}

          {/* Event 21 — closure refused, zero domain mutations. */}
          {p.governance ? (
            <GovernanceRefusal governance={p.governance} onOpenEvidence={onOpenEvidence} />
          ) : null}
        </div>
      ) : null}

      {tab === "evidence" ? (
        <EvidenceBranchPanel
          available={branchAvailable}
          active={branch}
          busy={branchBusy}
          proofLabel={p.branchState?.proofLabel ?? null}
          evidence={p.partnerEvidence?.[0]}
          custody={branchCustody}
          onEnter={onEnterBranch}
          onExit={onExitBranch}
        />
      ) : null}
    </>
  );
}

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
