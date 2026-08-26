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
import type { MapLocation, TomorrowView } from "../types/fullShelf";
import { schematicPoints } from "./schematicPoints";

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

/**
 * Saturday's candidate stops over the SAME six configured reference
 * locations the Today map uses.
 *
 * There is deliberately no drawn route here. No route geometry, polyline,
 * distance, ETA or position exists at any cursor, so a candidate stop is
 * placed at its configured site and connected to the hub by a dashed
 * assignment line that reads as intent, never as travel. Nothing on this
 * surface is telemetry: the runtime reports no position for any vehicle.
 */
function CandidateMap({ view, locations }: { view: TomorrowView; locations: MapLocation[] }) {
  const stops = view.candidateVehicles.flatMap((v) =>
    v.stops.map((s) => ({ ...s, vehicleId: v.vehicleId })),
  );

  const points = schematicPoints(locations);
  const hub = locations.find((l) => l.role === "HUB");
  const hubPoint = (hub && points.get(hub.id)) ?? [50, 50];

  // A candidate with no configured location is dropped, never placed at
  // an invented coordinate.
  const placed = stops
    .map((stop) => {
      const loc = locations.find(
        (l) => l.agencyId === stop.agencyId || l.orderIds?.includes(stop.orderId),
      );
      const point = loc && points.get(loc.id);
      return point ? { stop, loc: loc!, point } : null;
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);

  return (
    <div style={css(PANEL)} data-testid="saturday-candidate-map">
      <div style={css("flex:none;display:flex;align-items:baseline;justify-content:space-between;gap:10px")}>
        <span style={css("font-size:12.5px;font-weight:600;color:#eef4f4;white-space:nowrap")}>
          Candidate stops
        </span>
        <span
          className="mono"
          data-testid="saturday-map-provenance"
          style={css("font-size:8px;letter-spacing:.04em;color:#7e939c;text-align:right")}
        >
          CONFIGURED REFERENCE LOCATIONS · NO LIVE GPS
        </span>
      </div>

      <div
        style={css(
          "flex:1;min-height:0;margin-top:8px;border-radius:9px;overflow:hidden;position:relative;background:#12292f;border:1px solid #2b4c56",
        )}
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={css("position:absolute;inset:0;width:100%;height:100%")}>
          <g stroke="#1e3a42" strokeWidth="1.4">
            <path d="M0 25 H100 M0 50 H100 M0 75 H100" />
            <path d="M25 0 V100 M50 0 V100 M75 0 V100" />
          </g>
          {placed.map(({ stop, point }) => (
            <line
              key={stop.orderId}
              x1={hubPoint[0]}
              y1={hubPoint[1]}
              x2={point[0]}
              y2={point[1]}
              stroke="#4f97b0"
              strokeWidth=".7"
              strokeDasharray="1.8 1.4"
              opacity=".8"
            />
          ))}
        </svg>

        {hub ? (
          <div
            style={css(
              `position:absolute;left:${hubPoint[0]}%;top:${hubPoint[1]}%;transform:translate(-50%,-50%);` +
                "background:#16323b;border:1px solid #4f97b0;border-radius:7px;padding:5px 8px;white-space:nowrap",
            )}
          >
            <div className="mono" style={css("font-size:8px;font-weight:700;letter-spacing:.07em;color:#eef4f4")}>HUB</div>
          </div>
        ) : null}

        {placed.map(({ stop, loc, point }) => (
          <div
            key={stop.orderId}
            data-testid="saturday-candidate-stop"
            style={css(
              `position:absolute;left:${point[0]}%;top:${point[1]}%;transform:translate(-50%,-50%);` +
                "display:flex;align-items:center;gap:6px;background:#173139;border:1px dashed #4f97b0;" +
                "border-radius:7px;padding:5px 8px;white-space:nowrap",
            )}
          >
            <span
              className="mono"
              style={css(
                "width:17px;height:17px;border-radius:50%;display:flex;align-items:center;justify-content:center;" +
                  "background:#16323b;border:1px dashed #fff;color:#fff;font-size:7.5px;font-weight:700;flex:none",
              )}
            >
              {stop.sequence}
            </span>
            <div>
              <div style={css("font-size:9px;font-weight:600;color:#dce7e9")}>{loc.name}</div>
              <div className="mono" style={css("font-size:7.5px;color:#9fb4ba;margin-top:1px")}>
                {stop.cases ?? "—"} cases · candidate
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="mono" style={css("flex:none;font-size:8.5px;color:#7e939c;margin-top:7px;line-height:1.45")}>
        Constrained draft · candidate assignments are provisional and carry no delivery guarantee.
        No route, distance, ETA or vehicle position is shown, because none exists.
      </div>
    </div>
  );
}

export function SaturdayCandidatePlan({
  view,
  locations = [],
}: {
  view: TomorrowView;
  /** The runtime's six configured reference locations. */
  locations?: MapLocation[];
}) {
  return (
    <div style={css("flex:1;min-height:0;display:flex;flex-direction:column;margin-top:12px")} data-enter="">
      <div style={css("background:#f9f4f0;border:1px solid #e3c3ba;border-left:4px solid #a23b2b;border-radius:10px;padding:14px 16px;margin-bottom:14px")}>
        <div className="mono" style={css("font-size:10px;letter-spacing:.08em;color:#8a2f22;font-weight:600;line-height:1.4")}>
          FRIDAY UNRESOLVED CARRIES FORWARD
          <br />
          Agency 03 short 20 · Site 01 custody confirmation open · LTC-4471 excluded
        </div>
      </div>
      <div style={css("flex:none;display:flex;align-items:center;justify-content:space-between;gap:16px")}>
        <div>
          <h1 style={css("font-size:20px;font-weight:600;letter-spacing:-.01em;color:#16262c")}>
            Saturday’s candidate schedule
          </h1>
          <div style={css("font-size:12px;color:#5c6b71;margin-top:5px")}>
            Draft with constraints — no activation supported
          </div>
        </div>
        <span
          className="mono"
          style={css(
            "font-size:10.5px;font-weight:600;color:#8a5a12;background:#f7ecd6;border:1px solid #e6cf9e;" +
              "border-radius:6px;padding:5px 11px;flex:none;white-space:nowrap",
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
        {view.available ? (
          <CandidateMap view={view} locations={locations} />
        ) : (
          <UnavailablePanel reason={view.unavailableReason} />
        )}

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
          {view.inheritedObligations.length > 0 && (
            <div
              style={css("flex:none;background:#fff;border:1px solid #dfe4e0;border-radius:10px;overflow:hidden")}
              data-testid="planning-inputs"
            >
              <div style={css("background:#f7f8f6;padding:9px 13px")}>
                <span
                  className="mono"
                  style={css("font-size:9px;letter-spacing:.06em;color:#5c6b71;font-weight:700")}
                >
                  INHERITED CONSTRAINTS · {view.inheritedObligations.length} CARRY-FORWARD
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
          )}

          <div style={css("flex:none;background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:14px 16px;margin-top:12px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#5c6b71;font-weight:600;line-height:1.6")}>
              Tomorrow starts with yesterday's truth.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
