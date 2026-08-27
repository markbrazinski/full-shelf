import { useCallback, useMemo, useState } from "react";
import { css } from "../styles/css";
import type {
  CurrentDayView,
  DispatchStop,
  DispatchView,
  FleetVehicleView,
  MapLocation,
} from "../types/fullShelf";
import { PlannedDispatchMap, type PlannedStop } from "./PlannedDispatchMap";
import { schematicPoints } from "./schematicPoints";
import {
  ROUTE_ATTRIBUTION,
  ROUTE_COLORS,
  ROUTE_LABELS,
  type PlannedRoute,
} from "../data/contract/routeGeometry";
import { facilityName } from "../data/contract/facilityNames";

interface Props {
  currentDay: CurrentDayView;
  dispatch: DispatchView;
  /** Authoritative fleet, including vehicles no longer holding a manifest. */
  fleet?: FleetVehicleView[];
  mapsApiKey?: string;
  plannedStops: PlannedStop[];
  /** Committed reference routes that apply at this boundary. */
  routes: PlannedRoute[];
  /** The runtime's six configured reference locations. */
  locations: MapLocation[];
}

/** Match a stop to a configured location on projected identity only. */
function locationForStop(
  stop: { orderId: string; agency: string | null },
  locations: MapLocation[],
): MapLocation | undefined {
  const byOrder = locations.find((l) => l.orderIds?.includes(stop.orderId));
  if (byOrder) return byOrder;
  if (!stop.agency) return undefined;
  const agencyId = stop.agency.trim().toUpperCase().replace(/\s+/g, "-");
  return locations.find((l) => l.agencyId === agencyId);
}

const TONE = {
  delivered: { accent: "#3f7d5a", bg: "#e8f2ec", fg: "#2f6748" },
  planned: { accent: "#1f6f8b", bg: "#e8f1f4", fg: "#16536a" },
  impacted: { accent: "#a23b2b", bg: "#f5e8e4", fg: "#8a2f22" },
  reassigned: { accent: "#1f6f8b", bg: "#e8f1f4", fg: "#16536a" },
  partner: { accent: "#a85f12", bg: "#f8eedc", fg: "#8a5a12" },
  recall: { accent: "#a23b2b", bg: "#f5e8e4", fg: "#8a2f22" },
} as const;

export function TodayMapWorkspace({ currentDay, dispatch, fleet, mapsApiKey, plannedStops, routes, locations }: Props) {
  const [mapFailed, setMapFailed] = useState(false);
  const onMapFailure = useCallback(() => setMapFailed(true), []);
  const showGoogleMap = !!mapsApiKey && locations.length > 0 && !mapFailed;
  // The map heading says what the map shows. Provider identity is carried
  // by Google's own watermark, which is never covered or replaced.
  const mapLabel = "Planned routes";
  const manifests = useMemo(() => {
    const grouped = new Map<string, DispatchStop[]>();
    for (const stop of Object.values(dispatch.stops)) {
      const key = stop.vehicleId ?? "PARTNER_PICKUP";
      grouped.set(key, [...(grouped.get(key) ?? []), stop]);
    }
    return [...grouped.entries()]
      .map(([vehicleId, rows]) => ({
        vehicleId,
        label: vehicleId === "PARTNER_PICKUP"
          ? `Partner fulfillment · ${facilityName("PARTNER")}`
          : dispatch.vehicles[vehicleId === "TRUCK-01" ? "t1" : vehicleId === "TRUCK-02" ? "t2" : vehicleId]?.label ?? vehicleId,
        rows: rows.sort((a, b) => (a.sequence ?? 999) - (b.sequence ?? 999)),
      }))
      .sort((a, b) => a.vehicleId.localeCompare(b.vehicleId));
  }, [dispatch.stops, dispatch.vehicles]);
  const allRows = manifests.flatMap((m) => m.rows);
  // A commitment already DELIVERED under a superseded revision is still
  // part of today's work. The active dispatch block no longer carries it,
  // so it is read from the committed commitments instead.
  const deliveredCommitments = (currentDay.commitments ?? []).filter(
    (c) => c.stateTone === "delivered" && !allRows.some((r) => r.orderId === c.id),
  );
  const stopCount = allRows.length + deliveredCommitments.length;
  // Delivered and remaining PARTITION the day's cases: a delivered row is
  // never also counted as remaining, and a commitment already represented
  // by a manifest row is never re-added. 18 delivered + 78 remaining = 96.
  const deliveredCases =
    allRows.filter((r) => r.tone === "delivered").reduce((sum, r) => sum + (r.cases ?? 0), 0) +
    deliveredCommitments.reduce((sum, c) => sum + (c.cases ?? 0), 0);
  const remainingCases = allRows
    .filter((r) => r.tone !== "delivered")
    .reduce((sum, r) => sum + (r.cases ?? 0), 0);
  const caseCount = deliveredCases + remainingCases;

  // Vehicles the runtime still reports but that hold no active manifest —
  // a failed truck must stay visible rather than silently disappearing.
  const unavailableVehicles = (fleet ?? []).filter(
    (v) => !v.isOperational && !manifests.some((m) => m.vehicleId === v.vehicleId),
  );

  return (
    <section data-testid="today-map-workspace" style={css("display:flex;flex-direction:column;gap:12px") }>
      <div style={css("display:flex;align-items:flex-end;justify-content:space-between;gap:20px") }>
        <div>
          <div className="mono" style={css("font-size:10px;letter-spacing:.13em;color:#6d7f84;font-weight:700")}>TODAY · {currentDay.operatingDate}</div>
          <h1 style={css("font-size:25px;line-height:1.1;letter-spacing:-.025em;color:#172b32;margin-top:5px")}>Fulfillment workspace</h1>
          <div style={css("font-size:12px;color:#52666d;margin-top:5px")}>{dispatch.note}</div>
        </div>
        <div style={css("display:flex;gap:8px;align-items:stretch") }>
          <Metric label="PLAN" value={currentDay.authRev ?? "—"} />
          <Metric label="STOPS" value={String(stopCount)} />
          <Metric label="TOTAL CASES" value={String(caseCount)} testId="total-cases" />
          <Metric label="DELIVERED" value={String(deliveredCases)} testId="delivered-cases" />
          <Metric label="REMAINING" value={String(remainingCases)} testId="remaining-cases" />
        </div>
      </div>

      <div style={css("display:grid;grid-template-columns:minmax(0,1.65fr) minmax(340px,.9fr);gap:12px;min-height:0") }>
        <div data-testid="today-map" style={css("background:#fff;border:1px solid #d2d9d4;border-radius:11px;overflow:hidden;min-width:0") }>
          <div style={css("height:48px;padding:0 14px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e6e9e4") }>
            <div>
              <div style={css("font-size:13px;font-weight:700;color:#20353c")}>Planned dispatch</div>
              <div className="mono" style={css("font-size:9px;color:#7d8d92;margin-top:2px")}>COMMITTED ASSIGNMENTS</div>
            </div>
            <span data-testid="map-mode-label" className="mono" style={css("font-size:9px;font-weight:700;color:#8a5a12;background:#f8eedc;border:1px solid #ead3a9;border-radius:5px;padding:5px 8px")}>{mapLabel}</span>
          </div>
          <div style={css("padding:10px;background:#f5f6f2") }>
            {showGoogleMap ? (
              <PlannedDispatchMap
                stops={plannedStops}
                routes={routes}
                locations={locations}
                label={mapLabel}
                apiKey={mapsApiKey!}
                onFailure={onMapFailure}
              />
            ) : (
              <RouteSchematic
                stops={Object.values(dispatch.stops)}
                routes={routes}
                locations={locations}
              />
            )}
          </div>
        </div>

        <aside data-testid="truck-manifests" style={css("display:flex;flex-direction:column;gap:9px;min-width:0") }>
          <div style={css("display:flex;align-items:center;justify-content:space-between;padding:1px 2px 2px") }>
            <div>
              <div style={css("font-size:13px;font-weight:700;color:#20353c")}>Truck manifests</div>
              <div className="mono" style={css("font-size:9px;color:#7d8d92;margin-top:2px")}>COMMITTED MANIFEST ORDER</div>
            </div>
            <span className="mono" style={css("font-size:10px;color:#60747a")}>{manifests.length} assignments</span>
          </div>
          {manifests.map((manifest) => <Manifest key={manifest.vehicleId} vehicleId={manifest.vehicleId} label={manifest.label} stops={manifest.rows} />)}

          {/* A vehicle that lost its manifest stays in the fleet
              inventory, truthfully unavailable, with the work it already
              completed before it failed. */}
          {unavailableVehicles.map((v) => (
            <div
              key={v.vehicleId}
              data-testid="unavailable-vehicle"
              style={css("background:#fff;border:1px solid #e6bcb0;border-radius:10px;overflow:hidden")}
            >
              <div style={css("display:flex;align-items:center;justify-content:space-between;padding:9px 11px;background:#fdf5f3;border-bottom:1px solid #f0d5cd")}>
                <div style={css("display:flex;align-items:center;gap:8px")}>
                  <span style={css("width:8px;height:8px;border-radius:50%;background:#c0503a")} />
                  <strong style={css("font-size:11px;color:#20353c")}>{v.displayName}</strong>
                  <span className="mono" style={css("font-size:8px;color:#89969a")}>{v.vehicleId}</span>
                </div>
                <span className="mono" style={css("font-size:9px;color:#8a2f22;font-weight:700")}>
                  UNAVAILABLE
                </span>
              </div>
              <div className="mono" style={css("font-size:9.5px;color:#8a2f22;padding:8px 11px;line-height:1.5")}>
                {(v.status ?? "").replace(/_/g, " ").toLowerCase()} · holds no active manifest under the current plan
              </div>
              {deliveredCommitments
                .filter((c) => c.vehicle && c.vehicle.includes("1"))
                .map((c) => (
                  <div
                    key={c.id}
                    data-testid="delivered-commitment"
                    style={css("display:grid;grid-template-columns:27px minmax(0,1fr) auto;gap:8px;align-items:center;padding:8px 10px;border-top:1px solid #f3ece9")}
                  >
                    <span className="mono" style={css("width:23px;height:23px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;background:#e8f2ec;color:#2f6748")}>✓</span>
                    <div style={css("min-width:0")}>
                      <div style={css("display:flex;align-items:baseline;gap:6px")}>
                        <strong className="mono" style={css("font-size:10.5px;color:#20353c")}>{c.id}</strong>
                        <span style={css("font-size:11px;color:#40555c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")}>{facilityName(c.agency)}</span>
                      </div>
                      <div className="mono" style={css("font-size:8.5px;color:#839196;margin-top:2px")}>{c.lot}</div>
                    </div>
                    <div style={css("text-align:right")}>
                      <div className="mono" style={css("font-size:11px;font-weight:700;color:#20353c")}>{c.cases}</div>
                      <div className="mono" style={css("font-size:7.5px;color:#2f6748;text-transform:uppercase;margin-top:2px")}>delivered</div>
                    </div>
                  </div>
                ))}
            </div>
          ))}
        </aside>
      </div>
    </section>
  );
}

function Metric({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return <div data-testid={testId} style={css("min-width:72px;background:#fff;border:1px solid #d7ddd8;border-radius:8px;padding:8px 10px") }>
    <div className="mono" style={css("font-size:8.5px;letter-spacing:.1em;color:#839196;font-weight:700")}>{label}</div>
    <div className="mono" style={css("font-size:13px;color:#1d343c;font-weight:700;margin-top:2px")}>{value}</div>
  </div>;
}

function Manifest({ vehicleId, label, stops }: { vehicleId: string; label: string; stops: DispatchStop[] }) {
  const isPartner = vehicleId === "PARTNER_PICKUP";
  const cases = stops.reduce((sum, stop) => sum + (stop.cases ?? 0), 0);
  return <div style={css(`background:#fff;border:1px solid ${isPartner ? "#e5c990" : "#d2d9d4"};border-radius:10px;overflow:hidden`) }>
    <div style={css(`display:flex;align-items:center;justify-content:space-between;padding:9px 11px;background:${isPartner ? "#fbf2e2" : "#f7f8f5"};border-bottom:1px solid ${isPartner ? "#ead7b2" : "#e5e8e3"}`) }>
      <div style={css("display:flex;align-items:center;gap:8px") }><span style={css(`width:8px;height:8px;border-radius:50%;background:${isPartner ? "#a85f12" : "#1f6f8b"}`)} /><strong style={css("font-size:11px;color:#20353c")}>{label}</strong>{!isPartner ? <span className="mono" style={css("font-size:8px;color:#89969a")}>{vehicleId}</span> : null}</div>
      <span className="mono" style={css("font-size:9px;color:#6d7f84")}>{stops.length} stops · {cases} cases</span>
    </div>
    {stops.map((stop, index) => {
      const tone = TONE[stop.tone];
      return <div key={stop.orderId} style={css("display:grid;grid-template-columns:27px minmax(0,1fr) auto;gap:8px;align-items:center;padding:8px 10px;border-bottom:1px solid #eff1ed") }>
        <span className="mono" style={css(`width:23px;height:23px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;background:${tone.bg};color:${tone.fg}`)}>{stop.sequence ?? index + 1}</span>
        <div style={css("min-width:0") }><div style={css("display:flex;align-items:baseline;gap:6px") }><strong className="mono" style={css("font-size:10.5px;color:#20353c")}>{stop.orderId}</strong><span style={css("font-size:11px;color:#40555c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")}>{stop.agency ? facilityName(stop.agency) : facilityName("PARTNER")}</span></div><div className="mono" style={css("font-size:8.5px;color:#839196;margin-top:2px")}>{stop.lotId ?? "lot not reported"}</div></div>
        <div style={css("text-align:right") }><div className="mono" style={css("font-size:11px;font-weight:700;color:#20353c")}>{stop.cases ?? "—"}</div><div className="mono" style={css(`font-size:7.5px;color:${tone.fg};text-transform:uppercase;margin-top:2px`) }>{stop.tone}</div></div>
      </div>;
    })}
  </div>;
}

function RouteSchematic({
  stops,
  routes,
  locations,
}: {
  stops: DispatchStop[];
  routes: PlannedRoute[];
  locations: MapLocation[];
}) {
  const points = schematicPoints(locations);
  const hub = locations.find((l) => l.role === "HUB");
  const hubPoint = (hub && points.get(hub.id)) ?? [50, 50];

  // The fallback projects the SAME committed road geometry the Google
  // basemap draws, using the same lat/lon envelope as the site markers,
  // so the degraded surface is the same truth without a basemap under it.
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

  // A stop with no configured location is dropped rather than placed at
  // an invented coordinate.
  const placed = stops
    .map((stop) => {
      const loc = locationForStop(stop, locations);
      const point = loc && points.get(loc.id);
      return point ? { stop, loc: loc!, point } : null;
    })
    .filter((x): x is { stop: DispatchStop; loc: MapLocation; point: [number, number] } => x !== null);

  const legendRoles = Array.from(new Set(routes.map((r) => r.role)));

  return <div>
    <div data-testid="dispatch-svg-schematic" style={css("position:relative;height:410px;border:1px solid #d6ded9;border-radius:8px;overflow:hidden;background:#eef1ec") }>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={css("position:absolute;inset:0;width:100%;height:100%") }>
        <rect width="100" height="100" fill="#eef1ec" />
        {routes.map((route) => {
          if (route.path.length < 2) return null;
          const d = route.path
            .map((c, i) => `${i === 0 ? "M" : "L"}${project(c).map((n) => n.toFixed(2)).join(" ")}`)
            .join(" ");
          return (
            <path
              key={route.key}
              data-testid={`schematic-route-${route.role.toLowerCase()}`}
              d={d}
              fill="none"
              stroke={ROUTE_COLORS[route.role]}
              strokeWidth={route.role === "UNAVAILABLE" ? ".6" : ".85"}
              strokeDasharray={route.dashed ? "1.8 1.4" : undefined}
              strokeOpacity={route.role === "UNAVAILABLE" ? ".55" : ".95"}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          );
        })}
      </svg>
      {hub ? (
        <div style={css(`position:absolute;left:${hubPoint[0]}%;top:${hubPoint[1]}%;transform:translate(-50%,-50%);background:#16323b;color:#fff;border-radius:8px;padding:7px 9px;box-shadow:0 3px 10px rgba(22,50,59,.25);white-space:nowrap`) }>
          <div className="mono" style={css("font-size:8.5px;font-weight:700;letter-spacing:.08em")}>HUB</div>
          <div style={css("font-size:10px;color:#b8c9ce;margin-top:2px")}>{hub.name}</div>
        </div>
      ) : null}
      {placed.map(({ stop, loc, point }, index) => {
        const tone = TONE[stop.tone];
        return <div key={stop.orderId} style={css(`position:absolute;left:${point[0]}%;top:${point[1]}%;transform:translate(-50%,-50%);display:flex;align-items:center;gap:7px;background:#fff;border:1px solid #d2d9d4;border-left:4px solid ${tone.accent};border-radius:8px;padding:6px 8px;box-shadow:0 2px 7px rgba(31,51,57,.13);max-width:186px`)}><span className="mono" style={css(`width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:${tone.accent};color:#fff;font-size:8px;font-weight:700`)}>{stop.sequence ?? index + 1}</span><div style={css("min-width:0")}><div style={css("font-size:10px;font-weight:700;color:#20353c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap")}>{stop.orderId} · {loc.name}</div><div className="mono" style={css(`font-size:8.5px;color:${tone.fg};margin-top:2px`) }>{stop.cases ?? "—"} cases</div></div></div>;
      })}
    </div>
    <div style={css("display:flex;align-items:center;gap:13px;flex-wrap:wrap;margin-top:8px") }>
      {legendRoles.map((role) => (
        <span key={role} data-testid={`map-legend-${role.toLowerCase()}`} style={css("display:flex;align-items:center;gap:6px;font-size:11px;color:#43555c")}>
          <span data-legend-color={ROUTE_COLORS[role]} style={css(`width:16px;height:3px;border-radius:2px;background:${ROUTE_COLORS[role]}`)} />
          {ROUTE_LABELS[role]}
        </span>
      ))}
      <span className="mono" data-testid="schematic-provenance-label" style={css("margin-left:auto;font-size:9px;color:#75878c;letter-spacing:.02em")}>
        Planned routes
      </span>
    </div>
    <div className="mono" data-testid="map-location-disclosure" style={css("font-size:9.5px;color:#7d8d92;margin:4px 2px 0;letter-spacing:.02em;line-height:1.5")}>
      {ROUTE_ATTRIBUTION}
    </div>
  </div>;
}
