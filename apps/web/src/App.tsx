// =====================================================================
// Full Shelf v7 — Session-Driven Golden Journey
// =====================================================================
// Real session-based state machine. Events drive cursors, not beats.
// Nav/tabs select views only; they never advance or rewind time.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { css } from "./styles/css";
import { plannedStopsFrom } from "./data/contract/plannedStops";
import { googleMapsApiKey } from "./env";
import { GoldenRuntimeDataSource } from "./data/GoldenRuntimeDataSource";
import type { FullShelfProjection } from "./types/fullShelf";

import { TestModeBanner } from "./components/TestModeBanner";
import { TodayMapWorkspace } from "./components/TodayMapWorkspace";
import { RecallWorkspace } from "./components/RecallWorkspace";
import { HistoryLedger } from "./components/HistoryLedger";
import { ExecutionRecordDrawer } from "./components/ExecutionRecordDrawer";
import { SaturdayCandidatePlan } from "./components/SaturdayCandidatePlan";
import { ConnectionError } from "./components/ConnectionError";
import { ActivitySidecar } from "./components/ActivitySidecar";
import { RepairProposal } from "./components/RepairProposal";

const MAPS_API_KEY = googleMapsApiKey();

type View = "today" | "incident" | "history";
type Day = "fri" | "sat";

export default function App() {
  const [view, setView] = useState<View>("today");
  const [day, setDay] = useState<Day>("fri");
    const [projection, setProjection] = useState<FullShelfProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [execOpen, setExecOpen] = useState(false);
  const [sidecarOpen, setSidecarOpen] = useState(true);
  const [paused, setPaused] = useState(false);

  const backend = useRef(new GoldenRuntimeDataSource()).current;
  const sessionId = useRef<string>("");
  const unsubscribe = useRef<(() => void) | null>(null);
  const idempotencyKey = useRef<string>("");

  // Initialize session on mount
  useEffect(() => {
    (async () => {
      try {
        const snap = await backend.createSession();
        sessionId.current = snap.session_id;

        const proj = await backend.getProjection(snap.session_id);
        setProjection(proj);
        setLoading(false);

        // Subscribe to SSE first — set up listener before triggering events
        if (unsubscribe.current) unsubscribe.current();
        let lastEventId = "";
        unsubscribe.current = backend.subscribe(
          snap.session_id,
          lastEventId,
          async (envelope) => {
            lastEventId = envelope.event_id;

            // Event 11: Pause on Today if not in Incidents view
            if (envelope.sequence === 11 && view === "today") {
              await backend.pause(snap.session_id).catch(() => {});
              setPaused(true);
            }

            // Re-fetch projection for every committed event
            const updated = await backend.getProjection(snap.session_id);
            setProjection(updated);
          },
          (err) => {
            setError(err instanceof Error ? err.message : String(err));
          }
        );

        // Give SSE subscription a moment to be ready, then start autoplay
        await new Promise(resolve => setTimeout(resolve, 100));
        await backend.start(snap.session_id, 900);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      }
    })();

    return () => {
      if (unsubscribe.current) unsubscribe.current();
    };
  }, []);

  // Resume from event-11 pause when Incidents clicked
  useEffect(() => {
    if (paused && view === "incident" && sessionId.current) {
      (async () => {
        await backend.start(sessionId.current, 900);
        setPaused(false);
      })();
    }
  }, [view, paused, backend]);

  const reconnect = useCallback(async () => {
    if (!sessionId.current) return;
    try {
      setError(null);
      const proj = await backend.getProjection(sessionId.current);
      setProjection(proj);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [backend]);

  const approveRepair = useCallback(async () => {
    if (!sessionId.current || !projection?.repairProposal) {
      throw new Error("No active proposal");
    }

    if (!idempotencyKey.current) {
      idempotencyKey.current = crypto.randomUUID();
    }

    const proposal = projection.repairProposal;
    const binding = {
      plan_id: proposal.planId,
      incident_id: projection.incidentSummary.incidents[0]?.id ?? null,
      expected_revision: proposal.sourceRevision,
      target_revision: proposal.proposedRevision,
      actions: ["REROUTE", "PICKUP"],
      plan_diff_hash: proposal.planDiffHash,
      idempotency_key: idempotencyKey.current,
    };

    await backend.approve(sessionId.current, binding);
    // SSE will trigger projection update on event 9
  }, [projection, backend]);

  // Keyboard controls for presenter mode
  useEffect(() => {
    if (!sessionId.current) return;

    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, [contenteditable='true']")) return;

      if (e.code === "Space") {
        e.preventDefault();
        if (paused) {
          backend.start(sessionId.current, 900);
          setPaused(false);
        } else {
          backend.pause(sessionId.current);
          setPaused(true);
        }
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        backend.advance(sessionId.current);
      } else if (e.code === "KeyR") {
        e.preventDefault();
        (async () => {
          const snap = await backend.reset(sessionId.current);
          sessionId.current = snap.session_id;
          idempotencyKey.current = "";
          setPaused(false);
          const proj = await backend.getProjection(snap.session_id);
          setProjection(proj);
          await backend.start(snap.session_id, 900);
        })();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paused, backend]);

  const p = projection;
  const activeIncidents = p?.incidentSummary.activeCount ?? 0;
  const plannedStops = useMemo(
    () => (p?.dispatch ? plannedStopsFrom(p.dispatch) : []),
    [p?.dispatch]
  );

  if (error) {
    return (
      <div style={css("height:100vh;display:flex;flex-direction:column;background:#eef0ea")}>
        <ConnectionError detail={error} onReconnect={reconnect} />
      </div>
    );
  }

  return (
    <div
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
        <div style={css("display:flex;align-items:baseline;gap:9px")}>
          <span style={css("font-size:15px;font-weight:600;letter-spacing:-.01em")}>Full Shelf</span>
          <span className="mono" style={css("font-size:9.5px;letter-spacing:.14em;color:#7e939c")}>
            FULFILLMENT CONTROL PLANE
          </span>
        </div>
        <div style={css("display:flex;align-items:center;gap:10px")}>
          <span
            className="mono"
            style={css(
              "font-size:10.5px;color:#aebfc4;background:#1f3d47;border:1px solid #2b4c56;border-radius:5px;padding:4px 9px",
            )}
            data-testid="auth-rev"
          >
            {p?.currentDay.authRev ?? "—"}
          </span>
        </div>
        <div style={css("display:flex;align-items:center;gap:10px")}>
          <div style={css("text-align:right;line-height:1.2")}>
            <div className="mono" style={css("font-size:11.5px;font-weight:600")} data-testid="clock">
              {p?.currentDay.clock ?? "—"}
            </div>
            <div className="mono" style={css("font-size:9.5px;color:#8ea1a7")}>
              {p?.currentDay.operatingDate ?? ""}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setExecOpen(true)}
            style={css(
              "background:#1f3d47;color:#cfe0e4;border:1px solid #2b4c56;border-radius:6px;padding:6px 11px;" +
                "font-size:11.5px;font-weight:600;cursor:pointer",
            )}
          >
            Execution record
          </button>
        </div>
      </header>

      <div style={css("flex:1;display:flex;min-height:0")}>
        {/* LEFT NAV */}
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
                  style={css(
                    `font-size:13px;width:16px;text-align:center;color:${active ? "#8fc6da" : "#5e7982"}`,
                  )}
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
            "flex:1;min-width:0;display:flex;flex-direction:column;background:#eef0ea;overflow:auto;padding:14px 20px 16px",
          )}
        >
          {loading ? (
            <div
              style={css("flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:15px")}
            >
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
            <>
              {view === "today" ? (
                <>
                  {paused ? (
                    <div
                      style={css(
                        "flex:none;background:#f5e1dc;border:1px solid #e6bcb0;border-radius:8px;padding:12px 16px;" +
                          "margin-bottom:14px;font-size:13px;color:#8a2f22;font-weight:600",
                      )}
                    >
                      ⏸ Paused at event 11 — click Incidents to continue
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
                        onClick={() => setDay("sat")}
                        aria-pressed={day === "sat"}
                        data-testid="day-sat"
                        style={css(
                          `background:${day === "sat" ? "#16323b" : "transparent"};color:${day === "sat" ? "#eef4f4" : "#5c6b71"};` +
                            "border:none;border-radius:7px;padding:6px 13px;font-size:12px;font-weight:600;cursor:pointer",
                        )}
                      >
                        Saturday · Draft
                      </button>
                    </div>
                  </div>

                  {day === "sat" ? (
                    p.tomorrow ? (
                      <SaturdayCandidatePlan view={p.tomorrow} />
                    ) : (
                      <SaturdayCandidatePlan
                        view={{
                          available: false,
                          dayLabel: "Saturday",
                          planId: null,
                          revision: null,
                          status: null,
                          approvalRequired: false,
                          activationSupported: false,
                          candidateVehicles: [],
                          unassignedDemand: [],
                          inheritedObligations: [],
                          unavailableReason: "Next-day planning opens at 17:00",
                        }}
                      />
                    )
                  ) : (
                    <TodayMapWorkspace
                      currentDay={p.currentDay}
                      dispatch={p?.dispatch ?? { title: "", schematicLabel: "", note: "", stops: {}, vehicles: {}, capacityDecision: { beforeLabel: "", beforeValue: "", addLabel: "", addValue: "", afterLabel: "", afterValue: "", afterFillPct: 0, remainingLabel: "", remainingValue: "", needsLabel: "", needsValue: "", verdict: "", explain: "" } }}
                      mapsApiKey={MAPS_API_KEY}
                      plannedStops={plannedStops}
                    />
                  )}
                </>
              ) : view === "incident" ? (
                <RecallWorkspace
                  recall={p?.recall ?? { ref: "", banner: { title: "", body: "" }, intake: [], sourceExcerpt: "", sourceAnchoredLot: "", affectedCommitments: "", modelArmor: null }}
                  source={p.recallSource}
                  onToday={() => setView("today")}
                  onGo={() => {}}
                  onOpenEvidence={() => {}}
                />
              ) : (
                <HistoryLedger 
                  history={p?.history ?? { asOf: "", ledger: [], lineage: [], note: "" }}
                  onToday={() => setView("today")}
                />
              )}
            </>
          ) : null}
        </main>

        {/* SIDECAR */}
        {sidecarOpen && !loading && p ? (
          <aside
            style={css(
              "flex:none;width:400px;background:#16323b;color:#eef4f4;display:flex;flex-direction:column;" +
                "overflow:hidden;border-left:1px solid #0f1f23",
            )}
          >
            {p.repairProposal ? (
              <RepairProposal proposal={p.repairProposal} onApprove={approveRepair} />
            ) : null}
            <ActivitySidecar
              open={sidecarOpen}
              onToggle={() => setSidecarOpen(!sidecarOpen)}
              activity={p.agentActivity}
              governance={p.governance}
              onOpenExec={() => setExecOpen(true)}
            />
          </aside>
        ) : null}
      </div>

      {execOpen && p?.executionEvidence ? (
        <ExecutionRecordDrawer evidence={p.executionEvidence} onClose={() => setExecOpen(false)} />
      ) : null}
    </div>
  );
}
