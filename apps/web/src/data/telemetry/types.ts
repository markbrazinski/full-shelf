// =====================================================================
// Full Shelf — contextual vehicle telemetry (NON-AUTHORITATIVE)
// ---------------------------------------------------------------------
// Contextual demonstration evidence. This feed explains WHY a vehicle
// becomes unavailable. It never says WHAT Full Shelf committed in
// response — plans, revisions, orders, quantities and incidents come
// from the accepted projection and only from there.
//
// Two deliberately separate record kinds:
//
//   VehicleLocationSample  — where a vehicle reported itself to be
//   VehicleHealthEvent     — an explicit reported fault
//
// They are separate because GPS silence is not a fault. A stationary
// truck is usually just a truck at a stop. Only an explicit health
// event may place a vehicle in a failed contextual status; no amount of
// missing, repeated or stalled location samples may do so. That rule is
// mechanical (see `telemetryAt`), not stylistic.
// =====================================================================

/** Simulated telemetry is never live, measured or authoritative. */
export const TELEMETRY_CLASSIFICATION = "SIMULATED_TELEMETRY" as const;

export type TelemetryClassification = typeof TELEMETRY_CLASSIFICATION;

export interface VehicleLocationSample {
  sample_id: string;
  vehicle_id: string;
  /** ISO-8601 instant the sample was reported by the simulated source. */
  recorded_at: string;
  latitude: number;
  longitude: number;
  source_classification: TelemetryClassification;
}

/**
 * An explicit reported fault. Deliberately carries NO plan revision, no
 * affected orders and no recovery decision: those are authoritative and
 * belong to the projection.
 */
export interface VehicleHealthEvent {
  event_id: string;
  vehicle_id: string;
  event_type: "REFRIGERATION_FAILURE_REPORTED";
  reported_at: string;
  /** Who reported it — driver app, reefer controller, telematics platform. */
  source_type: string;
  source_classification: TelemetryClassification;
}

export interface TelemetryFeed {
  /** Stable identity of the checked-in fixture this feed came from. */
  fixture_id: string;
  samples: VehicleLocationSample[];
  health_events: VehicleHealthEvent[];
}

/**
 * The seam. A live or vendor adapter (driver app, fleet platform) can
 * implement this later without touching the map or the playback clock.
 */
export interface VehicleTelemetryDataSource {
  readonly classification: TelemetryClassification;
  /** Everything reported at or before `asOf`. Never anything after it. */
  feedAsOf(asOf: string): TelemetryFeed;
}
