// =====================================================================
// Full Shelf — Saturday candidate schedule (v6.1)
// ---------------------------------------------------------------------
// Every value here is read from `next_day_draft` in the accepted
// contract. There is NO fallback: when the contract returns no candidate
// assignments this renders an explicit unavailable panel with no routes,
// markers, manifests, assignments, loads, lots, or feasibility claims.
//
// A candidate is subordinate to DRAFT_WITH_CONSTRAINTS and is never an
// active commitment. No activation or approval control exists here,
// because no endpoint exists behind one.
// =====================================================================

import { css } from "../styles/css";
import type { TomorrowView } from "../types/fullShelf";

const PANEL = "background:#16323b;border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;color:#dce7e9;min-height:0";

function UnavailablePanel({ reason }: { reason: string | null }) {
  return (
    <div style={css(PANEL)} data-testid="saturday-unavailable">
      <div style={css("flex:none;display:flex;align-items:baseline;justify-content:space-between")}>
        <span style={css("font-size:12.5px;font-weight:600;color:#eef4f4;white-space:nowrap")}>
          Candidate dispatch map
        </span>
      </div>
      <div
        style={css(
          "flex:1;min-height:0;margin-top:8px;border-radius:9px;display:flex;flex-direction:column;" +
            "align-items:center;justify-content:center;gap:11px;background:#12292f;border:1px dashed #2b4c56;padding:24px",
        )}
      >
        <span
          className="mono"
          style={css(
            "font-size:9px;letter-spacing:.09em;font-weight:700;color:#8ea1a7;" +
              "background:#1f3d47;border:1px solid #2b4c56;border-radius:5px;padding:4px 9px",
          )}
        >
          CANDIDATE SCHEDULE UNAVAILABLE
        </span>
        <div style={css("font-size:12.5px;color:#c3d3d7;text-align:center;line-height:1.55;max-width:380px")}>
          No contract-backed candidate assignments were returned for this boundary.
        </div>
        {reason ? (
          <div
            className="mono"
            style={css("font-size:10px;color:#7e939c;text-align:center;line-height:1.5;max-width:380px")}
          >
            {reason}
          </div>
        ) : null}
      </div>
      <div className="mono" style={css("flex:none;font-size:8.5px;color:#7e939c;margin-top:7px;line-height:1.4")}>
        No routes, assignments, loads, or lots are shown, because none are committed.
      </div>
    </div>
  );
}

function CandidateMap({ view }: { view: TomorrowView }) {
  const stops = view.candidateVehicles.flatMap((v) =>
    v.stops.map((s) => ({ ...s, vehicleId: v.vehicleId })),
  );
  // Positions are laid out to fit the viewBox for any stop count, so a
  // third candidate stop cannot walk off the right edge. Geometry is
  // presentational; the facts are sequence, agency and cases.
  const at = (i: number) => {
    const span = Math.max(stops.length - 1, 1);
    return { x: 330 + (i - (stops.length - 1) / 2) * Math.min(150, 520 / span), y: 250 - i * 60 };
  };
  return (
    <div style={css(PANEL)} data-testid="saturday-candidate-map">
      <div style={css("flex:none;display:flex;align-items:baseline;justify-content:space-between")}>
        <span style={css("font-size:12.5px;font-weight:600;color:#eef4f4;white-space:nowrap")}>
          Candidate dispatch map
        </span>
        <span
          className="mono"
          style={css("font-size:8px;letter-spacing:.04em;color:#7e939c;margin-left:10px")}
        >
          SIMULATED TELEMETRY
        </span>
      </div>
      <div
        style={css(
          "flex:1;min-height:0;margin-top:8px;border-radius:9px;overflow:hidden;position:relative;background:#dfe5df",
        )}
      >
        <svg
          viewBox="0 0 660 430"
          width="100%"
          height="100%"
          preserveAspectRatio="xMidYMid slice"
          role="img"
          aria-labelledby="satmap"
          style={css("display:block")}
        >
          <title id="satmap">
            Saturday candidate dispatch map — hub, candidate stops, and unassigned demand. Candidate
            positions are simulated, not live GPS.
          </title>
          <g fill="#e8ede6">
            <rect x="20" y="18" width="150" height="86" rx="4" />
            <rect x="182" y="18" width="150" height="86" rx="4" />
            <rect x="344" y="18" width="140" height="86" rx="4" />
            <rect x="496" y="18" width="150" height="86" rx="4" />
            <rect x="20" y="118" width="150" height="96" rx="4" />
            <rect x="344" y="118" width="140" height="96" rx="4" />
            <rect x="496" y="118" width="150" height="96" rx="4" />
            <rect x="20" y="228" width="150" height="90" rx="4" />
            <rect x="182" y="228" width="150" height="90" rx="4" />
            <rect x="344" y="228" width="140" height="90" rx="4" />
            <rect x="20" y="332" width="150" height="80" rx="4" />
            <rect x="182" y="332" width="150" height="80" rx="4" />
            <rect x="344" y="332" width="140" height="80" rx="4" />
            <rect x="496" y="332" width="150" height="80" rx="4" />
          </g>
          <rect x="182" y="118" width="150" height="96" rx="6" fill="#d6e6cf" />
          <text x="257" y="170" textAnchor="middle" fill="#8fae82" fontSize="9" fontFamily="IBM Plex Mono">
            GREENWAY
          </text>
          <path d="M496 228 L646 246 L646 318 L496 300 Z" fill="#cfe0e6" />
          <text x="576" y="270" textAnchor="middle" fill="#8fb0bb" fontSize="9" fontFamily="IBM Plex Mono">
            RIVER
          </text>
          {/* Candidate route: dashed, because it is a draft, not a commitment. */}
          {stops.length > 0 ? (
            <path
              d={`M176 268 ${stops.map((_, i) => `L${at(i).x} ${at(i).y}`).join(" ")}`}
              fill="none"
              stroke="#4f97b0"
              strokeWidth="3.5"
              strokeDasharray="7 5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ) : null}
          <g>
            <rect x="158" y="252" width="36" height="32" rx="6" fill="#16323b" stroke="#4f97b0" strokeWidth="2" />
            <text
              x="176"
              y="272"
              textAnchor="middle"
              fill="#eef4f4"
              fontSize="9"
              fontFamily="IBM Plex Mono"
              fontWeight="700"
            >
              HUB
            </text>
          </g>
          <g fontFamily="IBM Plex Mono">
            {stops.map((s, i) => {
              const { x, y } = at(i);
              return (
                <g key={s.orderId}>
                  <circle
                    cx={x}
                    cy={y}
                    r="13"
                    fill="#16323b"
                    stroke="#fff"
                    strokeWidth="2"
                    strokeDasharray="4 3"
                  />
                  <text x={x} y={y + 4} textAnchor="middle" fill="#fff" fontSize="10" fontWeight="700">
                    {s.sequence}
                  </text>
                  <text x={x} y={y + 26} textAnchor="middle" fill="#3a4a50" fontSize="8">
                    {s.agency ?? "—"} · {s.cases ?? "—"}
                  </text>
                </g>
              );
            })}
            {view.unassignedDemand.map((u, i) => (
              <g key={u.shortfallId}>
                <circle
                  cx={250 + i * 110}
                  cy={330}
                  r="15"
                  fill="none"
                  stroke="#c98a2e"
                  strokeWidth="2.5"
                  strokeDasharray="5 4"
                />
                <text
                  x={250 + i * 110}
                  y={334}
                  textAnchor="middle"
                  fill="#8a5a12"
                  fontSize="9"
                  fontWeight="700"
                >
                  !
                </text>
                <text x={250 + i * 110} y={358} textAnchor="middle" fill="#8a5a12" fontSize="8.5">
                  unassigned · {u.cases ?? "—"}
                </text>
              </g>
            ))}
          </g>
        </svg>
      </div>
      <div className="mono" style={css("flex:none;font-size:8.5px;color:#7e939c;margin-top:7px;line-height:1.4")}>
        Constrained draft · candidate assignments are provisional and carry no delivery guarantee.
      </div>
    </div>
  );
}

export function SaturdayCandidatePlan({ view }: { view: TomorrowView }) {
  return (
    <div style={css("flex:1;min-height:0;display:flex;flex-direction:column;margin-top:12px")} data-enter="">
      <div style={css("flex:none;display:flex;align-items:center;justify-content:space-between;gap:16px")}>
        <h1 style={css("font-size:20px;font-weight:600;letter-spacing:-.01em;color:#16262c")}>
          Saturday’s distribution schedule
        </h1>
        <span
          className="mono"
          style={css(
            "font-size:10.5px;font-weight:600;color:#8a5a12;background:#f7ecd6;border:1px solid #e6cf9e;" +
              "border-radius:6px;padding:5px 11px",
          )}
          data-testid="saturday-status-chip"
        >
          {view.available ? `${view.status ?? "DRAFT"} · CANDIDATE` : "CANDIDATE PLAN UNAVAILABLE"}
        </span>
      </div>

      <div
        style={css(
          "flex:1;min-height:0;display:grid;grid-template-columns:1.15fr 1fr;gap:14px;margin-top:12px",
        )}
      >
        {view.available ? <CandidateMap view={view} /> : <UnavailablePanel reason={view.unavailableReason} />}

        <div style={css("min-height:0;display:flex;flex-direction:column;gap:10px;overflow:auto")}>
          {view.available
            ? view.candidateVehicles.map((v) => (
                <div
                  key={v.vehicleId ?? "unassigned"}
                  style={css(
                    "flex:none;background:#fff;border:1px dashed #b9cdd6;border-radius:11px;overflow:hidden",
                  )}
                  data-testid="candidate-manifest"
                >
                  <div style={css("padding:9px 13px 8px;border-bottom:1px solid #eef0ea;background:#fafbf9")}>
                    <div style={css("display:flex;align-items:center;gap:9px")}>
                      <span style={css("width:9px;height:9px;border-radius:2px;background:#4f97b0;flex:none")} />
                      <span style={css("font-size:13px;font-weight:600;color:#16262c;flex:1")}>
                        {v.vehicleId ?? "—"}
                      </span>
                      <span
                        className="mono"
                        style={css(
                          "font-size:8.5px;font-weight:700;color:#1f6f8b;background:#e2edf1;" +
                            "border:1px solid #bcd6e0;border-radius:4px;padding:2px 6px",
                        )}
                      >
                        CANDIDATE
                      </span>
                      <span className="mono" style={css("font-size:13px;font-weight:700;color:#16262c")}>
                        {v.candidateLoadCases}
                      </span>
                    </div>
                    <div
                      className="mono"
                      style={css("font-size:9px;color:#74848a;margin-top:5px;padding-left:18px")}
                    >
                      {v.stopCount} candidate stop{v.stopCount === 1 ? "" : "s"} · draft sequence
                    </div>
                  </div>
                  {v.stops.map((s) => (
                    <div key={s.orderId} style={css("padding:8px 13px;border-top:1px solid #f4f6f3")}>
                      <div style={css("display:flex;align-items:center;gap:8px")}>
                        <span
                          className="mono"
                          style={css("font-size:11px;font-weight:700;color:#1f6f8b;flex:none")}
                        >
                          {s.sequence}
                        </span>
                        <span style={css("font-size:12px;font-weight:600;color:#16262c;flex:1")}>
                          {s.agency ?? "—"}
                        </span>
                        <span className="mono" style={css("font-size:10px;color:#3a4a50")}>
                          {s.cases ?? "—"} cases
                        </span>
                      </div>
                      <div
                        style={css("display:flex;align-items:center;gap:8px;margin-top:4px;padding-left:14px")}
                      >
                        <span
                          className="mono"
                          style={css(
                            "font-size:9px;color:#256b4d;background:#e3f0e8;border:1px solid #bcd8c8;" +
                              "border-radius:4px;padding:2px 6px",
                          )}
                        >
                          {s.lotId ?? "—"}
                        </span>
                        <span className="mono" style={css("font-size:9px;color:#74848a")}>
                          {s.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ))
            : null}

          {/* Unassigned demand is committed state and is shown whenever it
              exists, including when no candidate assignments were returned. */}
          {view.unassignedDemand.map((u) => (
            <div
              key={u.shortfallId}
              style={css(
                "flex:none;background:#fdfaf3;border:1px solid #e6cf9e;border-left:4px solid #c98a2e;" +
                  "border-radius:10px;padding:10px 13px",
              )}
              data-testid="unassigned-demand"
            >
              <span
                className="mono"
                style={css(
                  "font-size:8.5px;font-weight:700;color:#8a5a12;background:#f7ecd6;border-radius:4px;padding:2px 6px",
                )}
              >
                UNASSIGNED DELIVERY DEMAND
              </span>
              <div style={css("font-size:12px;font-weight:600;color:#16262c;margin-top:6px")}>
                {u.agencyId ?? "—"} · {u.cases ?? "—"} cases unassigned
              </div>
              <div style={css("font-size:10.5px;color:#8a5a12;margin-top:2px;line-height:1.4")}>
                {u.reason
                  ? u.reason.replace(/_/g, " ").toLowerCase()
                  : "Remains open pending sourcing."}
              </div>
            </div>
          ))}

          {/* Carry-forwards are committed obligations, shown in both states. */}
          {view.inheritedObligations.length > 0 ? (
            <div
              style={css("flex:none;background:#fff;border:1px solid #dfe4e0;border-radius:10px;overflow:hidden")}
              data-testid="planning-inputs"
            >
              <div style={css("background:#f7f8f6;padding:9px 13px")}>
                <span
                  className="mono"
                  style={css("font-size:9px;letter-spacing:.06em;color:#5c6b71;font-weight:700")}
                >
                  PLANNING INPUTS · {view.inheritedObligations.length} CARRY-FORWARD
                  {view.inheritedObligations.length === 1 ? "" : "S"}
                </span>
              </div>
              <div style={css("padding:4px 11px 10px;display:flex;flex-direction:column;gap:7px")}>
                {view.inheritedObligations.map((o) => (
                  <div
                    key={o.id}
                    style={css(
                      "border:1px solid #eef0ea;border-left:3px solid #c14a34;border-radius:8px;" +
                        "padding:8px 11px;background:#fafbf9",
                    )}
                  >
                    <span
                      className="mono"
                      style={css(
                        "font-size:8px;font-weight:700;letter-spacing:.05em;color:#9a3322;" +
                          "background:#f5e1dc;border-radius:4px;padding:2px 6px",
                      )}
                    >
                      {o.badge}
                    </span>
                    <div
                      style={css("font-size:11.5px;font-weight:600;color:#16262c;margin-top:5px;line-height:1.35")}
                    >
                      {o.title}
                    </div>
                    <div style={css("font-size:10px;color:#5c6b71;margin-top:2px;line-height:1.4")}>
                      {o.origin}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
