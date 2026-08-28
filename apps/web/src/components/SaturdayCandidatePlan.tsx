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
import { useCallback, useState } from "react";
import { schematicPoints } from "./schematicPoints";
import { PlannedDispatchMap, type PlannedStop } from "./PlannedDispatchMap";
import {
  ROUTE_ATTRIBUTION,
  ROUTE_COLORS,
  saturdayRoute,
  type PlannedRoute,
} from "../data/contract/routeGeometry";
import { facilityName } from "../data/contract/facilityNames";

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
 * Saturday's candidate route over the SAME six configured reference
 * locations, using the SAME real Google Maps implementation and the same
 * truthful fallback as Today.
 *
 * The drawn line is committed CONFIGURED_REFERENCE_ROUTE geometry
 * (hub -> Berkeley -> Alameda -> hub) and is dashed because the plan is a
 * candidate. Nothing here is telemetry: the runtime reports no position
 * for any vehicle, and no ETA or distance is claimed.
 *
 * East Oakland's 20 cases are unassigned demand: the site is shown, and
 * it is deliberately NOT connected to the route.
 */
function CandidateMap({
  view,
  locations,
  mapsApiKey,
}: {
  view: TomorrowView;
  locations: MapLocation[];
  mapsApiKey?: string;
}) {
  const [mapFailed, setMapFailed] = useState(false);
  const onFailure = useCallback(() => setMapFailed(true), []);
  const showGoogleMap = !!mapsApiKey && locations.length > 0 && !mapFailed;
  const mapLabel = "Candidate route";

  const stops = view.candidateVehicles.flatMap((v) =>
    v.stops.map((s) => ({ ...s, vehicleId: v.vehicleId })),
  );

  // Candidate stops carry Truck 2's identity; unassigned demand does not
  // join the route and is drawn as demand only.
  const plannedStops: PlannedStop[] = stops.map((s) => ({
    orderId: s.orderId,
    agency: s.agencyId,
    cases: s.cases,
    sequence: s.sequence,
    kind: "REVISED",
    vehicleId: s.vehicleId ?? "TRUCK-02",
  }));

  const route = saturdayRoute();

  return (
    <div style={css(PANEL)} data-testid="saturday-candidate-map">
      <div style={css("flex:none;display:flex;align-items:baseline;justify-content:space-between;gap:10px")}>
        <span style={css("font-size:12.5px;font-weight:600;color:#eef4f4;white-space:nowrap")}>
          Candidate route
        </span>
        <span
          className="mono"
          data-testid="saturday-map-provenance"
          style={css("font-size:8px;letter-spacing:.04em;color:#7e939c;text-align:right")}
        >
          {mapLabel}
        </span>
      </div>

      <div style={css("flex:1;min-height:0;margin-top:8px;background:#f5f6f2;border-radius:9px;padding:8px")}>
        {showGoogleMap ? (
          <PlannedDispatchMap
            stops={plannedStops}
            routes={[route]}
            locations={locations}
            label={mapLabel}
            apiKey={mapsApiKey!}
            onFailure={onFailure}
            showAttribution={false}
          />
        ) : (
          <SaturdaySchematic
            stops={plannedStops}
            route={route}
            locations={locations}
          />
        )}
      </div>

      {/* ONE disclosure, in the panel's fixed footer. Both the map and the
          schematic used to render the route attribution themselves, from
          inside the flex:1 body — so it overflowed the map container and
          printed on top of this line. */}
      <div
        className="mono"
        data-testid="map-location-disclosure"
        style={css("flex:none;font-size:8.5px;color:#7e939c;margin-top:7px;line-height:1.45")}
      >
        {`Constrained draft · candidate assignments are provisional and carry no delivery guarantee. ${ROUTE_ATTRIBUTION}.`}
      </div>
    </div>
  );
}

/** Truthful fallback: the same committed geometry, without a basemap. */
function SaturdaySchematic({
  stops,
  route,
  locations,
}: {
  stops: PlannedStop[];
  route: PlannedRoute;
  locations: MapLocation[];
}) {
  const points = schematicPoints(locations);
  const hub = locations.find((l) => l.role === "HUB");
  const hubPoint = (hub && points.get(hub.id)) ?? [50, 50];

  const lats = locations.map((l) => l.lat);
  const lons = locations.map((l) => l.lon);
  const [minLat, maxLat] = [Math.min(...lats), Math.max(...lats)];
  const [minLon, maxLon] = [Math.min(...lons), Math.max(...lons)];
  const spanLat = maxLat - minLat || 1;
  const spanLon = maxLon - minLon || 1;
  const project = ([lat, lon]: [number, number]): [number, number] => [
    14 + ((lon - minLon) / spanLon) * 72,
    12 + ((maxLat - lat) / spanLat) * 76,
  ];

  const placed = stops
    .map((stop) => {
      const loc = locations.find(
        (l) => l.agencyId === stop.agency || l.orderIds?.includes(stop.orderId),
      );
      const point = loc && points.get(loc.id);
      return point ? { stop, loc: loc!, point } : null;
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);

  const d = route.path
    .map((c, i) => `${i === 0 ? "M" : "L"}${project(c).map((n) => n.toFixed(2)).join(" ")}`)
    .join(" ");

  return (
    <div>
      <div
        data-testid="dispatch-svg-schematic"
        style={css("position:relative;height:330px;border:1px solid #d6ded9;border-radius:8px;overflow:hidden;background:#eef1ec")}
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={css("position:absolute;inset:0;width:100%;height:100%")}>
          <rect width="100" height="100" fill="#eef1ec" />
          <path
            data-testid="saturday-route-line"
            d={d}
            fill="none"
            stroke={ROUTE_COLORS.TRUCK_2}
            strokeWidth=".85"
            strokeDasharray="1.8 1.4"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        </svg>
        {hub ? (
          <div
            style={css(
              `position:absolute;left:${hubPoint[0]}%;top:${hubPoint[1]}%;transform:translate(-50%,-50%);` +
                "background:#16323b;color:#fff;border-radius:7px;padding:5px 8px;white-space:nowrap",
            )}
          >
            <div className="mono" style={css("font-size:8px;font-weight:700;letter-spacing:.07em")}>HUB</div>
            <div style={css("font-size:9.5px;color:#b8c9ce;margin-top:1px")}>{hub.name}</div>
          </div>
        ) : null}
        {placed.map(({ stop, loc, point }) => (
          <div
            key={stop.orderId}
            data-testid="saturday-candidate-stop"
            style={css(
              `position:absolute;left:${point[0]}%;top:${point[1]}%;transform:translate(-50%,-50%);` +
                "display:flex;align-items:center;gap:6px;background:#fff;border:1px dashed #1f6f8b;" +
                "border-radius:7px;padding:5px 8px;white-space:nowrap",
            )}
          >
            <span
              className="mono"
              style={css(
                "width:17px;height:17px;border-radius:50%;display:flex;align-items:center;justify-content:center;" +
                  `background:${ROUTE_COLORS.TRUCK_2};color:#fff;font-size:7.5px;font-weight:700;flex:none`,
              )}
            >
              T2-{stop.sequence}
            </span>
            <div>
              <div style={css("font-size:9.5px;font-weight:700;color:#20353c")}>{loc.name}</div>
              <div className="mono" style={css("font-size:8px;color:#5f6f74;margin-top:1px")}>
                {stop.cases ?? "—"} cases · candidate
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SaturdayCandidatePlan({
  view,
  locations = [],
  mapsApiKey,
}: {
  view: TomorrowView;
  /** The runtime's six configured reference locations. */
  locations?: MapLocation[];
  mapsApiKey?: string;
}) {
  const assignedCases = view.candidateVehicles.reduce(
    (n, v) => n + (v.candidateLoadCases ?? 0),
    0,
  );
  const unassignedCases = view.unassignedDemand.reduce((n, u) => n + (u.cases ?? 0), 0);

  return (
    <div style={css("flex:1;min-height:0;display:flex;flex-direction:column;margin-top:12px")} data-enter="">
      <div style={css("flex:none;display:flex;align-items:center;justify-content:space-between;gap:16px")}>
        <div>
          <h1 style={css("font-size:20px;font-weight:600;letter-spacing:-.01em;color:#16262c")}>
            Saturday’s candidate schedule
          </h1>
          <div style={css("font-size:12px;color:#5c6b71;margin-top:5px")}>
            Draft with constraints
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

      {/* Saturday's headline result, stated as one message. */}
      <div
        data-testid="saturday-primary-message"
        style={css(
          "flex:none;background:#f4f8f4;border:1px solid #cfe0d6;border-left:4px solid #2f7d5b;" +
            "border-radius:10px;padding:11px 15px;margin-top:11px;display:flex;align-items:center;gap:14px;flex-wrap:wrap",
        )}
      >
        <span style={css("font-size:14px;font-weight:700;color:#16262c")}>
          Saturday draft: {assignedCases} cases assigned · {unassignedCases} cases still unassigned.
        </span>
      </div>

      {/* Fleet availability. Truck 1's return to service is not an
          authoritative field in this contract, so it is shown as
          unconfirmed rather than predicted. */}
      <div
        data-testid="saturday-fleet-availability"
        style={css(
          "flex:none;display:flex;gap:10px;margin-top:10px;flex-wrap:wrap",
        )}
      >
        <div
          data-testid="fleet-truck-1"
          style={css(
            "flex:1;min-width:230px;background:#fff;border:1px solid #e6bcb0;border-left:4px solid #c0503a;" +
              "border-radius:9px;padding:9px 12px",
          )}
        >
          <div style={css("font-size:12px;font-weight:700;color:#16262c")}>Truck 1 — unavailable</div>
          <div className="mono" style={css("font-size:9.5px;color:#8a2f22;margin-top:3px")}>
            refrigeration failed · Return time not confirmed
          </div>
        </div>
        <div
          data-testid="fleet-truck-2"
          style={css(
            "flex:1;min-width:230px;background:#fff;border:1px solid #bcd6e0;border-left:4px solid #1f6f8b;" +
              "border-radius:9px;padding:9px 12px",
          )}
        >
          <div style={css("font-size:12px;font-weight:700;color:#16262c")}>Truck 2 — available</div>
          <div className="mono" style={css("font-size:9.5px;color:#16536a;margin-top:3px")}>
            60-case capacity
          </div>
        </div>
      </div>

      <div
        style={css(
          "flex:1;min-height:0;display:grid;grid-template-columns:1.15fr 1fr;gap:14px;margin-top:12px",
        )}
      >
        {view.available ? (
          <CandidateMap view={view} locations={locations} mapsApiKey={mapsApiKey} />
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
                          {facilityName(s.agencyId) || s.agency || "—"}
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
                {facilityName(u.agencyId) || u.agencyId || "—"} · {u.cases ?? "—"} cases unassigned
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

        </div>
      </div>
    </div>
  );
}
