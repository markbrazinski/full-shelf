// =====================================================================
// Full Shelf — configured reference route geometry
// ---------------------------------------------------------------------
// Road-following polylines between the runtime's configured facilities,
// fetched ONCE from OSRM (OpenStreetMap data) by
// scripts/fetch_reference_routes.py and committed as coordinates.
//
// This is CONFIGURED_REFERENCE_ROUTE geometry: which roads a planned
// route would follow between configured facilities. It is NOT a travelled
// route, a driven path, live GPS, or evidence that any vehicle moved. No
// ETA, distance or duration is carried, and nothing is fetched at render
// or capture time.
//
// Which route applies is decided by the committed plan revision, never by
// a clock or a guess.
// =====================================================================

import routes from "./referenceRoutes.json";

export const ROUTE_ATTRIBUTION = routes.attribution;
export const ROUTE_CLASSIFICATION = routes.classification;

export type RouteKey =
  | "T1_REV07"
  | "T2_REV07"
  | "T2_REV08"
  | "PARTNER_REV08"
  | "T2_SATURDAY";

/** Per-vehicle visual identity. Truck 1 and partner must never collide. */
export type RouteRole = "TRUCK_1" | "TRUCK_2" | "PARTNER" | "UNAVAILABLE";

export const ROUTE_COLORS: Record<RouteRole, string> = {
  // Coral/rust — Truck 1 only.
  TRUCK_1: "#c0503a",
  // Teal/blue — Truck 2 only.
  TRUCK_2: "#1f6f8b",
  // Amber, always dashed — partner fulfilment only.
  PARTNER: "#b3781f",
  // Muted grey — a failed or unavailable vehicle's withdrawn route.
  UNAVAILABLE: "#8d9a9e",
};

export const ROUTE_LABELS: Record<RouteRole, string> = {
  TRUCK_1: "Truck 1",
  TRUCK_2: "Truck 2",
  PARTNER: "Partner fulfillment",
  UNAVAILABLE: "Truck 1 · unavailable",
};

/** Committed geometry for a leg, as [lat, lng] pairs. */
export function routePath(key: RouteKey): [number, number][] {
  // The JSON import widens each pair to number[]; the generator writes
  // strictly two-element [lat, lng] pairs and a test enforces that shape.
  const table = routes.routes as unknown as Record<string, [number, number][]>;
  return table[key] ?? [];
}

export interface PlannedRoute {
  key: RouteKey;
  role: RouteRole;
  /** Dashed strokes read as planned intent, never as a travelled path. */
  dashed: boolean;
  path: [number, number][];
}

/**
 * The routes that apply at a committed boundary.
 *
 * Before rev08 activates, Truck 1 holds its three stops. Once Truck 1's
 * refrigeration fails the route is shown withdrawn (muted grey) rather
 * than deleted, so the failure is legible. After rev08 activates, Truck 2
 * carries Alameda and East Oakland becomes partner fulfilment.
 */
export function routesForBoundary({
  truck1Failed,
  rev08Active,
}: {
  truck1Failed: boolean;
  rev08Active: boolean;
}): PlannedRoute[] {
  if (rev08Active) {
    return [
      { key: "T2_REV08", role: "TRUCK_2", dashed: false, path: routePath("T2_REV08") },
      { key: "PARTNER_REV08", role: "PARTNER", dashed: true, path: routePath("PARTNER_REV08") },
    ];
  }
  return [
    {
      key: "T1_REV07",
      role: truck1Failed ? "UNAVAILABLE" : "TRUCK_1",
      dashed: truck1Failed,
      path: routePath("T1_REV07"),
    },
    { key: "T2_REV07", role: "TRUCK_2", dashed: false, path: routePath("T2_REV07") },
  ];
}

/** Saturday's candidate route: hub → Berkeley → Alameda → hub. */
export function saturdayRoute(): PlannedRoute {
  return { key: "T2_SATURDAY", role: "TRUCK_2", dashed: true, path: routePath("T2_SATURDAY") };
}
