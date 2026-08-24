// =====================================================================
// Full Shelf — vehicle marker layer for the Google map
// ---------------------------------------------------------------------
// Draws SIMULATED_TELEMETRY vehicle markers over the authoritative
// planned-route drawing, keeping the two visibly distinct: planned
// routes are lines between configured facilities; vehicles are round
// markers labelled with the last REPORTED sample time.
//
// Marker motion between samples is a tween for legibility. The tooltip
// always quotes the actual sample, never the tween frame.
// =====================================================================

import type { VehicleTelemetryState } from "../data/telemetry/playback";

export const VEHICLE_STYLE = {
  REPORTING: { fill: "#1f6f8b", stroke: "#ffffff" },
  FAULT_REPORTED: { fill: "#a23b2b", stroke: "#f3e5e1" },
} as const;

export const VEHICLE_LABEL: Record<string, string> = {
  "TRUCK-01": "T1",
  "TRUCK-02": "T2",
};

/**
 * Tooltip text. Says `Last sample · HH:MM` — the reported instant — and
 * never "current position", "live" or "last reported".
 */
export function vehicleTitle(v: VehicleTelemetryState): string {
  const name = VEHICLE_LABEL[v.vehicleId] ?? v.vehicleId;
  const status =
    v.contextualStatus === "FAULT_REPORTED"
      ? "Refrigeration alarm received"
      : "Replay · simulated telematics";
  return `${name} · Last sample · ${v.lastSampleTime} · ${status}`;
}

/** Creates or moves one marker per vehicle. Returns the marker registry. */
export function syncVehicleMarkers(
  maps: any,
  map: any,
  vehicles: VehicleTelemetryState[],
  registry: Map<string, any>,
): Map<string, any> {
  for (const v of vehicles) {
    const style = VEHICLE_STYLE[v.contextualStatus];
    const position = { lat: v.renderLat, lng: v.renderLng };
    const existing = registry.get(v.vehicleId);
    if (existing) {
      existing.setPosition(position);
      existing.setTitle(vehicleTitle(v));
      existing.setIcon(icon(maps, style));
      continue;
    }
    registry.set(
      v.vehicleId,
      new maps.Marker({
        map,
        position,
        title: vehicleTitle(v),
        zIndex: 900,
        label: { text: VEHICLE_LABEL[v.vehicleId] ?? "V", color: "#ffffff", fontSize: "11px", fontWeight: "700" },
        icon: icon(maps, style),
      }),
    );
  }
  return registry;
}

const icon = (maps: any, style: { fill: string; stroke: string }) => ({
  path: maps.SymbolPath.CIRCLE,
  scale: 12,
  fillColor: style.fill,
  fillOpacity: 1,
  strokeColor: style.stroke,
  strokeWeight: 3,
});
