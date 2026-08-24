import { useCallback, useEffect, useRef, useState } from "react";
import { css } from "./styles/css";
import { BEATS } from "./data/contract/beats";
import { plannedStopsFrom } from "./data/contract/plannedStops";
import { createDataSource, googleMapsApiKey, isReplayMode } from "./env";
import type { FullShelfDataSource } from "./data/FullShelfDataSource";
import type { BeatId, Connection, FullShelfProjection } from "./types/fullShelf";

import { TestModeBanner } from "./components/TestModeBanner";
import { StateNavigator } from "./components/StateNavigator";
import { TopBar } from "./components/TopBar";
import { DaybookHeader } from "./components/DaybookHeader";
import { AgentActivityRail } from "./components/AgentActivityRail";
import { CommitmentsBoard } from "./components/CommitmentsBoard";
import { RevisionReview } from "./components/RevisionReview";
import { DispatchSchematic } from "./components/DispatchSchematic";
import { RecallWorkspace } from "./components/RecallWorkspace";
import { IncidentRail } from "./components/IncidentRail";
import { CustodyGraph } from "./components/CustodyGraph";
import { GovernedRecovery } from "./components/GovernedRecovery";
import { GovernanceRefusal } from "./components/GovernanceRefusal";
import { TodaysOutcome } from "./components/TodaysOutcome";
import { TomorrowsDraft } from "./components/TomorrowsDraft";
import { HistoryLedger } from "./components/HistoryLedger";
import { ExecutionRecordDrawer } from "./components/ExecutionRecordDrawer";

// Runtime truth comes from the accepted contract over HTTP — deterministic
// replay or the live orchestrator, selected by VITE_DATA_SOURCE. The Design
// fixture is NOT reachable from this entry path; it is test/reference material.
const dataSource: FullShelfDataSource = createDataSource();

const MAPS_API_KEY = googleMapsApiKey();
// Provenance is stated differently for synthetic replay vs configured live
// locations, but neither ever claims a live vehicle position.
const MAP_LABEL = isReplayMode()
  ? "Synthetic replay · Google planned dispatch · not live vehicle tracking"
  : "Google planned dispatch · configured facility locations · not live vehicle tracking";

const TODAY_HOME: Partial<Record<BeatId, BeatId>> = {
  revisionReview: "truckFailure",
  dispatchSchematic: "truckFailure",
  tomorrowsDraft: "todaysOutcome",
};

export default function App() {
  const [beat, setBeat] = useState<BeatId>("healthy");
  const [lastBeat, setLastBeat] = useState<BeatId>("healthy");
  const [projection, setProjection] = useState<FullShelfProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [connectionOverride, setConnectionOverride] = useState<Connection | null>(null);
  const reqBeat = useRef<BeatId>("healthy");

  const loadBeat = useCallback((next: BeatId) => {
    reqBeat.current = next;
    setBeat(next);
    if (next !== "history") setLastBeat(next);
    setLoading(true);
    setError(null);
    setEvidenceOpen(false);
    setConnectionOverride(null);
    dataSource
      .getProjection(next)
      .then((proj) => {
        if (reqBeat.current === next) {
          setProjection(proj);
          setLoading(false);
        }
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    loadBeat("healthy");
  }, [loadBeat]);

  const goToday = useCallback(() => loadBeat(TODAY_HOME[lastBeat] ?? lastBeat), [lastBeat, loadBeat]);
  const goHistory = useCallback(() => loadBeat("history"), [loadBeat]);
  const openEvidence = useCallback(() => setEvidenceOpen(true), []);
  const toggleConnection = useCallback(() => setConnectionOverride((c) => (c ? null : "DISCONNECTED")), []);

  const p = projection;
  const cd = p?.currentDay;
  const isHistory = beat === "history";
  const connection: Connection = connectionOverride ?? cd?.connection ?? "CONNECTED";
  const disconnected = !!connectionOverride;
  const isIncidentRail = beat === "custodyEstablished" || beat === "governedRecovery" || beat === "governanceRefusal";

  return (
    <div style={css("width:1280px;margin:0 auto;padding:16px 0 40px")}>
      <TestModeBanner dataMode={p?.dataMode ?? "SYNTHETIC_TEST"} />
      <StateNavigator beats={BEATS} activeBeat={beat} onGo={loadBeat} />

      <div style={css("position:relative;background:#f4f2ec;min-height:900px;border-radius:12px;box-shadow:0 1px 3px rgba(22,50,59,.14);display:flex;flex-direction:column;overflow:hidden")}>
        <TopBar
          clock={loading ? "—" : (cd?.clock ?? "—")}
          operatingDate={loading ? "" : (cd?.operatingDate ?? "")}
          connection={connection}
          isHistory={isHistory}
          onToday={goToday}
          onHistory={goHistory}
          onOpenEvidence={openEvidence}
          onToggleConnection={toggleConnection}
        />

        {disconnected && (
          <div style={css("background:#f3e5e1;border-bottom:1px solid #e3c3ba;padding:9px 28px;display:flex;align-items:center;gap:12px;flex:none")}>
            <span className="mono" style={css("font-size:12px;color:#a23b2b;font-weight:700")}>■ DISCONNECTED</span>
            <span style={css("font-size:12px;color:#8a2f22")}>Live updates are paused. Showing the last projection received as of {p?.asOf ?? "—"}. No authoritative state changes while disconnected.</span>
          </div>
        )}

        {isHistory && !loading && p?.history && (
          <div style={css("background:#eef1ee;border-bottom:1px solid #dfe4e0;padding:9px 28px;display:flex;align-items:center;gap:12px;flex:none")}>
            <span className="mono" style={css("font-size:11px;font-weight:600;letter-spacing:.08em;color:#5c6b71")}>REVIEWING PROVENANCE · AS OF {p.history.asOf}</span>
            <span style={css("font-size:12px;color:#5c6b71")}>Read-only. Reviewing history does not change today's authoritative state.</span>
            <span role="button" tabIndex={0} onClick={goToday} onKeyDown={(e) => e.key === "Enter" && goToday()} style={css("margin-left:auto;font-size:12px;font-weight:600;color:#1f6f8b;cursor:pointer")}>Return to current Today →</span>
          </div>
        )}

        <div style={css("flex:1;padding:24px 28px 26px")}>
          {loading && (
            <div style={css("display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:560px;gap:16px")}>
              <span className="fs-spin" style={css("width:34px;height:34px;border-radius:50%;border:3px solid #dfe4e0;border-top-color:#1f6f8b")} />
              <div className="mono" style={css("font-size:12px;letter-spacing:.08em;color:#74848a")}>Loading projection…</div>
            </div>
          )}

          {error && (
            <div style={css("display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:560px;gap:10px")}>
              <div className="mono" style={css("font-size:13px;color:#a23b2b;font-weight:600")}>Projection unavailable</div>
              <div style={css("font-size:12px;color:#74848a")}>{error}</div>
            </div>
          )}

          {!loading && !error && p && cd && (
            <>
              {cd.inDaybook && <DaybookHeader cd={cd} onGo={loadBeat} />}
              {p.agentActivity && <AgentActivityRail view={p.agentActivity} onOpenEvidence={openEvidence} />}

              {cd.commitments && <CommitmentsBoard cd={cd} onHistory={goHistory} onOpenEvidence={openEvidence} />}

              {p.incident?.diffRows && (
                <RevisionReview incident={p.incident} onToday={goToday} onGo={loadBeat} onApprove={() => loadBeat("rev08Active")} />
              )}

              {p.dispatch && (
                <DispatchSchematic
                  dispatch={p.dispatch}
                  onToday={goToday}
                  onGo={loadBeat}
                  mapsApiKey={MAPS_API_KEY}
                  plannedStops={plannedStopsFrom(p.dispatch)}
                  mapLabel={MAP_LABEL}
                />
              )}

              {beat === "recallProcessing" && p.recall && (
                <RecallWorkspace recall={p.recall} onToday={goToday} onGo={loadBeat} onOpenEvidence={openEvidence} />
              )}

              {isIncidentRail && (
                <IncidentRail
                  ref_={p.incident?.ref ?? "INC-2231"}
                  postureLabel={p.incident?.posture ?? "PARTIALLY_CONTAINED"}
                  activeBeat={beat}
                  onToday={goToday}
                  onGo={loadBeat}
                />
              )}
              {p.custody && <CustodyGraph custody={p.custody} onOpenEvidence={openEvidence} />}
              {p.recovery && <GovernedRecovery recovery={p.recovery} onOpenEvidence={openEvidence} />}
              {p.governance && <GovernanceRefusal governance={p.governance} onOpenEvidence={openEvidence} />}

              {p.outcome && <TodaysOutcome outcome={p.outcome} onGo={loadBeat} />}
              {p.tomorrow && <TomorrowsDraft tomorrow={p.tomorrow} onGo={loadBeat} />}
              {p.history && <HistoryLedger history={p.history} onToday={goToday} />}
            </>
          )}
        </div>
      </div>

      {evidenceOpen && <ExecutionRecordDrawer evidence={p?.executionEvidence} onClose={() => setEvidenceOpen(false)} />}
    </div>
  );
}
