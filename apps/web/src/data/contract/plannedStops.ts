// =====================================================================
// Full Shelf — planned stops for the dispatch map
// ---------------------------------------------------------------------
// Reads structured contract facts straight off the normalized
// DispatchView. Nothing here parses a display string: order id, agency,
// case count and sequence are all projected fields.
//
// `sequence` is COMMITTED_MANIFEST_ORDER (see the projection's
// sequence_basis). It is an ordering of committed rows, never a routing
// or travel-time optimization, and must not be presented as one.
//
// Classification is read from the stop's own tone, which the normalizer
// set from the contract's assignment_type/status — never guessed here.
//
//   ORIGINAL = the superseded Truck 1 plan (muted/red)
//   REVISED  = the active Truck 2 plan (blue)
//   PARTNER  = refrigerated partner pickup (amber)
// =====================================================================

import type { Commitment, DispatchView } from "../../types/fullShelf";
import type { PlannedStop } from "../../components/PlannedDispatchMap";

/**
 * Map stops for a boundary.
 *
 * `delivered` carries commitments that were completed under a superseded
 * revision. A later revision re-plans the REMAINING work and drops them
 * from dispatch, but the delivery still happened, so those stops stay on
 * the map rather than vanishing when the plan changes.
 */
export function plannedStopsFrom(
  dispatch: DispatchView,
  delivered: Commitment[] = [],
): PlannedStop[] {
  const stops: PlannedStop[] = Object.values(dispatch.stops).map((stop) => ({
    orderId: stop.orderId,
    agency: stop.agency,
    cases: stop.cases,
    // A partner pickup holds no position on any vehicle manifest. It is
    // still drawn, so it falls back to 0 rather than being dropped.
    sequence: stop.sequence ?? 0,
    // Marker ownership is decided by the runtime's assignment, so the
    // vehicle id travels with the stop rather than being inferred.
    vehicleId: stop.vehicleId,
    kind:
      stop.tone === "partner"
        ? "PARTNER"
        : stop.tone === "impacted" || stop.tone === "delivered"
          ? "ORIGINAL"
          : "REVISED",
  }));

  const seen = new Set(stops.map((s) => s.orderId));
  for (const c of delivered) {
    if (seen.has(c.id)) continue;
    stops.push({
      orderId: c.id,
      agency: c.agency,
      cases: c.cases,
      // A completed delivery holds no position in the ACTIVE manifest;
      // it is drawn at its site with the vehicle that carried it.
      sequence: 0,
      vehicleId: c.vehicle?.includes("1") ? "TRUCK-01" : c.vehicle ?? null,
      kind: "ORIGINAL",
    });
  }
  return stops;
}
