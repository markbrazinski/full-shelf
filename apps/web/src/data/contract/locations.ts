// =====================================================================
// DEMO_TENANT_LOCATION_REFERENCE
// ---------------------------------------------------------------------
// Location CONFIGURATION for the demo tenant, not operational evidence.
//
// This directory maps stable facility identifiers supplied by the
// backend (agency labels, vehicle hubs, staging) to reference
// coordinates chosen for the demo tenant. It is frontend presentation
// configuration in exactly the same sense as a street address on a
// printed route sheet.
//
// It is NOT, and must never be rendered as:
//   - a GPS fix, live position, or telemetry reading
//   - a vehicle's current or last-known location
//   - a bearing, heading, speed, or "last reported" time
//   - evidence that anything physically occurred at these coordinates
//
// The backend supplies WHAT is planned (stop order, orders, cases,
// assignment, capacity). This file supplies only WHERE a named facility
// is configured to sit so a planned route can be drawn. If the two ever
// disagree, the backend is authoritative and this file is wrong.
// =====================================================================

export const LOCATION_CLASSIFICATION = "DEMO_TENANT_LOCATION_REFERENCE" as const;

export interface ReferenceLocation {
  /** Stable facility key correlated to backend agency/vehicle labels. */
  key: string;
  label: string;
  kind: "HUB" | "AGENCY" | "STAGING";
  lat: number;
  lng: number;
}

// Reference coordinates in the East Bay, matching the demo tenant's
// configured service area. Chosen for legibility of the planned-route
// drawing; no facility here is a real address.
export const DEMO_TENANT_LOCATIONS: ReferenceLocation[] = [
  { key: "HUB",       label: "Food Bank Warehouse", kind: "HUB",     lat: 37.8044, lng: -122.2712 },
  { key: "Agency 01", label: "Agency 01",           kind: "AGENCY",  lat: 37.8716, lng: -122.2727 },
  { key: "Agency 02", label: "Agency 02",           kind: "AGENCY",  lat: 37.8358, lng: -122.2691 },
  { key: "Agency 03", label: "Agency 03",           kind: "AGENCY",  lat: 37.7749, lng: -122.2194 },
  { key: "Agency 04", label: "Agency 04",           kind: "AGENCY",  lat: 37.8534, lng: -122.1808 },
  { key: "Agency 05", label: "Agency 05",           kind: "AGENCY",  lat: 37.7649, lng: -122.1861 },
  { key: "STAGING",   label: "Pickup Staging",      kind: "STAGING", lat: 37.8199, lng: -122.2585 },
];

const BY_KEY = new Map(DEMO_TENANT_LOCATIONS.map((l) => [l.key, l]));

/**
 * Resolve a backend-supplied facility label to configured coordinates.
 * Returns undefined when the tenant has no configured location — the
 * caller must degrade, never invent a coordinate.
 */
export function locationFor(key: string | null | undefined): ReferenceLocation | undefined {
  return key ? BY_KEY.get(key) : undefined;
}
