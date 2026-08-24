// =====================================================================
// Full Shelf v6.1 — fulfillment control plane
// ---------------------------------------------------------------------
// A persistent shell: header, left nav, workspace, activity sidecar. The
// shell never disappears between moments; only the workspace changes.
//
// Every factual value comes from the accepted contract over HTTP
// (deterministic replay or the live orchestrator, selected in env.ts).
// The Design fixture is NOT reachable from this entry path.
//
// Two rules this file exists to keep:
//   * The incident badge is read from projection.incidentSummary, never
//     inferred from which view is open.
//   * A datasource failure shows the connection-error surface, and
//     Reconnect performs a real retry.
// =====================================================================

import { useCallback, useEffect, useRef, useState } from "react";
import { css } from "./styles/css";
import { plannedStopsFrom } from "./data/contract/plannedStops";
import { createDataSource, googleMapsApiKey, isReplayMode } from "./env";
import type { FullShelfDataSource } from "./data/FullShelfDataSource";
import type { BeatId, FullShelfProjection } from "./types/fullShelf";

import { TestModeBanner } from "./components/TestModeBanner";
import { AgentActivityRail } from "./components/AgentActivityRail";
import { CommitmentsBoard } from "./components/CommitmentsBoard";
import { RevisionReview } from "./components/RevisionReview";
import { DispatchSchematic } from "./components/DispatchSchematic";
import { RecallWorkspace } from "./components/RecallWorkspace";
import { CustodyGraph } from "./components/CustodyGraph";
import { GovernedRecovery } from "./components/GovernedRecovery";
import { GovernanceRefusal } from "./components/GovernanceRefusal";
import { HistoryLedger } from "./components/HistoryLedger";
import { ExecutionRecordDrawer } from "./components/ExecutionRecordDrawer";
import { SaturdayCandidatePlan } from "./components/SaturdayCandidatePlan";
import { ConnectionError } from "./components/ConnectionError";
import { ActivitySidecar } from "./components/ActivitySidecar";
import { RepairProposal } from "./components/RepairProposal";

const dataSource: FullShelfDataSource = createDataSource();
const MAPS_API_KEY = googleMapsApiKey();
const MAP_LABEL = isReplayMode()
  ? "Synthetic replay · Google planned dispatch · not live vehicle tracking"
  : "Google planned dispatch · configured facility locations · not live vehicle tracking";

type View = "today" | "incident" | "history";
type Day = "fri" | "sat";
type IncidentTab = "scope" | "custody" | "response" | "evidence";

/** Which boundary each surface reads. Every value is an explicit as_of. */
// Three Friday moments: the healthy plan, the moment the fault has been
// reported and a proposal is pending approval, and the committed update.
const FRIDAY_HEALTHY: BeatId = "healthy";
const FRIDAY_PROPOSED: BeatId = "revisionReview";
const FRIDAY_DISRUPTED: BeatId = "rev08Active";
const SATURDAY: BeatId = "tomorrowsDraft";
// Each tab reads the first boundary at which its evidence is actually
// committed. Custody reconciliation commits at 10:10, not at the 10:05
// beat label: asking earlier truthfully returns
// custody_graph = NOT_COMMITTED_AS_OF_BOUNDARY.
// Scope the approval to the tenant and day this client is bound to. The
// operator identity is NEVER hardcoded: it comes from the verified token the
// orchestrator checks, not from anything here.
const TENANT_ID = "east-bay-food-bank";
const OPERATING_DAY = "2026-08-14";

const INCIDENT_TAB_BEAT: Record<IncidentTab, BeatId> = {
  scope: "recallProcessing",
  custody: "governedRecovery",
  response: "governanceRefusal",
  evidence: "governanceRefusal",
};

export default function App() {
  const [view, setView] = useState<View>("today");
  const [day, setDay] = useState<Day>("fri");
  const [friday, setFriday] = useState<BeatId>(FRIDAY_HEALTHY);
  const [incidentTab, setIncidentTab] = useState<IncidentTab>("scope");
  const [projection, setProjection] = useState<FullShelfProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [execOpen, setExecOpen] = useState(false);
  const [sidecarOpen, setSidecarOpen] = useState(true);
  const pending = useRef<BeatId | null>(null);

  const beat: BeatId =
    view === "history"
      ? "history"
      : view === "incident"
        ? INCIDENT_TAB_BEAT[incidentTab]
        : day === "sat"
          ? SATURDAY
          : friday;

  const load = useCallback((next: BeatId) => {
    pending.current = next;
    setLoading(true);
    setError(null);
    dataSource
      .getProjection(next)
      .then((proj) => {
        if (pending.current !== next) return;
        setProjection(proj);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (pending.current !== next) return;
        // A datasource failure is surfaced, never swallowed. The control
        // plane shows nothing rather than stale or unverified data.
        setProjection(null);
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    load(beat);
  }, [beat, load]);

  /** A real retry against the same boundary, not a cosmetic reset. */
  const reconnect = useCallback(() => load(beat), [beat, load]);

  /**
   * Approve the pending proposal through the real verified-human -> KMS ->
   * ledger path, then reload this boundary exactly once. On success the
   * proposal disappears because the revision it repairs is no longer active;
   * on failure the error surfaces and nothing changed.
   */
  const approveRepair = useCallback(async () => {
    const proposal = projection?.repairProposal;
    if (!proposal?.planId || !proposal.sourceRevision || !proposal.proposedRevision) {
      throw new Error("PROPOSAL_INCOMPLETE — nothing was submitted.");
    }
    await dataSource.approveRepair({
      proposalId: proposal.proposalId,
      tenantId: TENANT_ID,
      operatingDay: OPERATING_DAY,
      incidentId: projection?.incidentSummary.incidents[0]?.id ?? "",
      planId: proposal.planId,
      sourceRevision: proposal.sourceRevision,
      proposedRevision: proposal.proposedRevision,
      planDiff: {
        rerouteOrderId: proposal.rerouteOrderId,
        rerouteCases: proposal.rerouteCases,
        rerouteTargetVehicle: proposal.rerouteTargetVehicle,
        pickupOrderId: proposal.pickupOrderId,
        pickupCases: proposal.pickupCases,
      },
    });
    // One reload after commitment: the map and manifests update once.
    setFriday(FRIDAY_DISRUPTED);
  }, [projection, load]);

  const p = projection;
  const activeIncidents = p?.incidentSummary.activeCount ?? 0;

  if (error) {
    return (
      <div style={css("height:100vh;display:flex;flex-direction:column;background:#eef0ea")}>
        <ConnectionError detail={error} onReconnect={reconnect} />
      </div>
    );
  }

  return (
    <div style={css("height:100vh;display:flex;flex-direction:column;background:#eef0ea;overflow:hidden")}>
      <TestModeBanner dataMode={p?.dataMode ?? "SYNTHETIC_TEST"} />

      {/* ---------------------------- HEADER ---------------------------- */}
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
        {/* --------------------------- LEFT NAV --------------------------- */}
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
                {/* Derived from the projection's incidents, never from view state. */}
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
          <div style={css("margin-top:auto;border-top:1px solid #1e3a42;padding-top:10px")}>
            <div
              className="mono"
              style={css("font-size:8.5px;color:#5e7982;letter-spacing:.04em;padding:8px 12px 2px;line-height:1.5")}
            >
              FLEET · 5 AGENTS
              <br />
              MODEL ARMOR BOUNDARY
            </div>
          </div>
        </nav>

        {/* -------------------------- WORKSPACE -------------------------- */}
        <main
          style={css(
            "flex:1;min-width:0;display:flex;flex-direction:column;background:#eef0ea;overflow:auto;padding:14px 20px 16px",
          )}
        >
          {loading ? (
            <div
              style={css(
                "flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:15px",
              )}
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
                  <div
                    style={css(
                      "flex:none;display:flex;align-items:center;justify-content:space-between;gap:16px",
                    )}
                  >
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
                    {day === "fri" ? (
                      <div style={css("display:flex;background:#e2e6df;border-radius:9px;padding:3px")}>
                        {(
                          [
                            [FRIDAY_HEALTHY, "08:05 · healthy", "moment-healthy"],
                            [FRIDAY_PROPOSED, "08:21 · fault reported", "moment-proposed"],
                            [FRIDAY_DISRUPTED, "08:24 · updated plan", "moment-updated"],
                          ] as [BeatId, string, string][]
                        ).map(([id, label, tid]) => {
                          const on = friday === id;
                          return (
                            <button
                              key={id}
                              type="button"
                              onClick={() => setFriday(id)}
                              aria-pressed={on}
                              data-testid={tid}
                              style={css(
                                `background:${on ? "#16323b" : "transparent"};color:${on ? "#eef4f4" : "#5c6b71"};` +
                                  "border:none;border-radius:7px;padding:6px 11px;font-size:11px;font-weight:600;cursor:pointer",
                              )}
                            >
                              {label}
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>

                  {day === "sat" ? (
                    p.tomorrow ? (
                      <SaturdayCandidatePlan view={p.tomorrow} />
                    ) : (
                      // The contract carried no draft at this boundary. No
                      // fallback: the surface says so and shows nothing.
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
                          unavailableReason:
                            "The contract returned no next-day draft at this boundary.",
                        }}
                      />
                    )
                  ) : (
                    <div style={css("margin-top:12px;display:flex;flex-direction:column;gap:14px")}>
                      {p.agentActivity ? (
                        <AgentActivityRail view={p.agentActivity} onOpenEvidence={() => setExecOpen(true)} />
                      ) : null}
                      {p.repairProposal ? (
                        <RepairProposal
                          proposal={p.repairProposal}
                          alarm={{
                            vehicleId: p.repairProposal.failedVehicleId,
                            receivedAt: p.currentDay.clock,
                            source: "SIMULATED FLEET TELEMATICS",
                          }}
                          onApprove={approveRepair}
                        />
                      ) : null}
                      {p.currentDay.commitments ? (
                        <CommitmentsBoard
                          cd={p.currentDay}
                          onHistory={() => setView("history")}
                          onOpenEvidence={() => setExecOpen(true)}
                        />
                      ) : null}
                      {p.dispatch ? (
                        <DispatchSchematic
                          dispatch={p.dispatch}
                          onToday={() => setView("today")}
                          onGo={() => setView("today")}
                          mapsApiKey={MAPS_API_KEY}
                          plannedStops={plannedStopsFrom(p.dispatch)}
                          mapLabel={MAP_LABEL}
                        />
                      ) : null}
                    </div>
                  )}
                </>
              ) : null}

              {view === "incident" ? (
                <>
                  <div
                    style={css(
                      "flex:none;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap",
                    )}
                  >
                    <div style={css("display:flex;align-items:center;gap:10px;min-width:0")}>
                      <h1 style={css("font-size:18px;font-weight:600;color:#16262c;white-space:nowrap")}>
                        {p.incident?.ref ?? p.incidentSummary.incidents[0]?.id ?? "Incident"}
                      </h1>
                      {p.incidentSummary.incidents.map((i) => (
                        <span
                          key={i.id}
                          className="mono"
                          data-testid="incident-status"
                          style={css(
                            "font-size:10px;color:#8a5a12;background:#f7ecd6;border:1px solid #e6cf9e;" +
                              "border-radius:6px;padding:4px 8px;font-weight:600;white-space:nowrap",
                          )}
                        >
                          {i.id} · {i.status}
                        </span>
                      ))}
                    </div>
                    <div style={css("display:flex;background:#e2e6df;border-radius:9px;padding:3px")}>
                      {(["scope", "custody", "response", "evidence"] as IncidentTab[]).map((t) => {
                        const active = incidentTab === t;
                        return (
                          <button
                            key={t}
                            type="button"
                            onClick={() => setIncidentTab(t)}
                            aria-current={active ? "true" : "false"}
                            data-testid={`tab-${t}`}
                            style={css(
                              `background:${active ? "#16323b" : "transparent"};color:${active ? "#eef4f4" : "#5c6b71"};` +
                                "border:none;border-radius:7px;padding:6px 15px;font-size:12px;font-weight:600;cursor:pointer;text-transform:capitalize",
                            )}
                          >
                            {t}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div style={css("margin-top:13px;display:flex;flex-direction:column;gap:14px")}>
                    {incidentTab === "scope" && p.recall ? (
                      <RecallWorkspace
                        recall={p.recall}
                        source={p.recallSource}
                        onToday={() => setView("today")}
                        onGo={() => setView("today")}
                        onOpenEvidence={() => setExecOpen(true)}
                      />
                    ) : null}
                    {incidentTab === "custody" && p.custody ? (
                      <CustodyGraph custody={p.custody} onOpenEvidence={() => setExecOpen(true)} />
                    ) : null}
                    {incidentTab === "response" ? (
                      <>
                        {p.recovery ? (
                          <GovernedRecovery recovery={p.recovery} onOpenEvidence={() => setExecOpen(true)} />
                        ) : null}
                        {p.governance ? (
                          <GovernanceRefusal governance={p.governance} onOpenEvidence={() => setExecOpen(true)} />
                        ) : null}
                      </>
                    ) : null}
                    {incidentTab === "evidence" ? (
                      <>
                        {p.incident?.diffRows ? (
                          <RevisionReview
                            incident={p.incident}
                            onToday={() => setView("today")}
                            onGo={() => setView("today")}
                            onApprove={() => setView("today")}
                          />
                        ) : null}
                        <button
                          type="button"
                          onClick={() => setExecOpen(true)}
                          style={css(
                            "align-self:flex-start;background:#16323b;color:#eef4f4;border:none;border-radius:7px;" +
                              "padding:8px 14px;font-size:12px;font-weight:600;cursor:pointer",
                          )}
                        >
                          Open full Execution Record →
                        </button>
                      </>
                    ) : null}
                  </div>
                </>
              ) : null}

              {view === "history" && p.history ? (
                <HistoryLedger history={p.history} onToday={() => setView("today")} />
              ) : null}

              {/* Fields the contract could not truthfully reconstruct here. */}
              {p.omittedFields.length > 0 ? (
                <div
                  className="mono"
                  style={css("flex:none;margin-top:12px;font-size:9px;color:#9aa6ab;line-height:1.6")}
                  data-testid="omitted-fields"
                >
                  {p.omittedFields.map((f) => (
                    <div key={f}>not available at this boundary · {f}</div>
                  ))}
                </div>
              ) : null}
            </>
          ) : null}
        </main>

        <ActivitySidecar
          open={sidecarOpen}
          onToggle={() => setSidecarOpen((o) => !o)}
          activity={p?.agentActivity}
          governance={p?.governance}
          onOpenExec={() => setExecOpen(true)}
        />
      </div>

      {execOpen ? (
        <ExecutionRecordDrawer evidence={p?.executionEvidence} onClose={() => setExecOpen(false)} />
      ) : null}
    </div>
  );
}
