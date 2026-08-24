// =====================================================================
// Full Shelf — telemetry playback against the presentation clock
// ---------------------------------------------------------------------
// Resolves "where was each vehicle, and what fault had been reported"
// at a given projection boundary. Deterministic: the same boundary
// always yields the same result.
//
// THE RULE, enforced here and nowhere else:
//
//   contextualStatus === "FAULT_REPORTED"  IFF  a VehicleHealthEvent
//   for that vehicle exists at or before the boundary.
//
// Stale samples, repeated coordinates and total GPS silence all leave
// the status "REPORTING". A vehicle that stopped moving is a vehicle
// that stopped moving.
// =====================================================================

import { minutesOf } from "./fixture";
import type {
  TelemetryFeed,
  VehicleHealthEvent,
  VehicleLocationSample,
  VehicleTelemetryDataSource,
} from "./types";

export interface VehicleTelemetryState {
  vehicleId: string;
  /** The last ACTUAL sample. Tooltips quote this, never a tween frame. */
  lastSample: VehicleLocationSample;
  /** Where to draw the marker now — may be interpolated between samples. */
  renderLat: number;
  renderLng: number;
  /** True when renderLat/renderLng are a tween, not a reported sample. */
  interpolated: boolean;
  /** "08:20" — formatted from lastSample.recorded_at, for `Last sample · HH:MM`. */
  lastSampleTime: string;
  contextualStatus: "REPORTING" | "FAULT_REPORTED";
  /** Present only when an explicit health event was reported. */
  healthEvent?: VehicleHealthEvent;
}

export interface TelemetryPlayback {
  fixtureId: string;
  vehicles: VehicleTelemetryState[];
  /** Every health event reported at or before the boundary. */
  healthEvents: VehicleHealthEvent[];
}

const hhmm = (iso: string) => /T(\d{2}:\d{2})/.exec(iso)?.[1] ?? "—";

/**
 * @param atMinutes Presentation-clock position, minutes from midnight.
 *   Fractional values tween between samples for smooth motion; the
 *   reported sample time is unaffected.
 */
export function playbackAt(
  source: VehicleTelemetryDataSource,
  asOf: string,
  atMinutes = minutesOf(asOf),
): TelemetryPlayback {
  const feed: TelemetryFeed = source.feedAsOf(asOf);
  const byVehicle = new Map<string, VehicleLocationSample[]>();
  for (const s of feed.samples) {
    // Belt and braces: the source already filters, but a future adapter
    // must not be able to leak a post-boundary sample through here.
    if (minutesOf(s.recorded_at) > minutesOf(asOf)) continue;
    const list = byVehicle.get(s.vehicle_id) ?? [];
    list.push(s);
    byVehicle.set(s.vehicle_id, list);
  }

  const vehicles: VehicleTelemetryState[] = [];
  for (const [vehicleId, list] of [...byVehicle].sort((a, b) => a[0].localeCompare(b[0]))) {
    const health = feed.health_events.find((e) => e.vehicle_id === vehicleId);
    // A faulted vehicle is frozen at its last reported sample: no tween
    // past a position it never reported.
    const frozen = !!health;
    const { lat, lng, base, interpolated } = positionAt(list, frozen ? Infinity : atMinutes);

    vehicles.push({
      vehicleId,
      lastSample: base,
      renderLat: lat,
      renderLng: lng,
      interpolated,
      lastSampleTime: hhmm(base.recorded_at),
      // Only the explicit event may produce a fault. Nothing about
      // `list` — its length, staleness or repetition — is consulted.
      contextualStatus: health ? "FAULT_REPORTED" : "REPORTING",
      ...(health ? { healthEvent: health } : {}),
    });
  }

  return { fixtureId: feed.fixture_id, vehicles, healthEvents: feed.health_events };
}

/** Last sample at/before `atMinutes`, tweened toward the next if one exists. */
function positionAt(list: VehicleLocationSample[], atMinutes: number) {
  const sorted = [...list].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at));
  let i = 0;
  while (i + 1 < sorted.length && minutesOf(sorted[i + 1].recorded_at) <= atMinutes) i++;
  const base = sorted[i];
  const next = sorted[i + 1];
  if (!next) return { lat: base.latitude, lng: base.longitude, base, interpolated: false };

  const t0 = minutesOf(base.recorded_at);
  const t1 = minutesOf(next.recorded_at);
  const f = Math.min(1, Math.max(0, (atMinutes - t0) / (t1 - t0 || 1)));
  return {
    lat: base.latitude + (next.latitude - base.latitude) * f,
    lng: base.longitude + (next.longitude - base.longitude) * f,
    base, // the tooltip's source of truth stays the reported sample
    interpolated: f > 0,
  };
}
