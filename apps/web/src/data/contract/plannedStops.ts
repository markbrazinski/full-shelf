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

import type { DispatchView } from "../../types/fullShelf";
import type { PlannedStop } from "../../components/PlannedDispatchMap";

export function plannedStopsFrom(dispatch: DispatchView): PlannedStop[] {
  return Object.values(dispatch.stops).map((stop) => ({
    orderId: stop.orderId,
    agency: stop.agency,
    cases: stop.cases,
    // A partner pickup holds no position on any vehicle manifest. It is
    // still drawn, so it falls back to 0 rather than being dropped.
    sequence: stop.sequence ?? 0,
    kind:
      stop.tone === "partner"
        ? "PARTNER"
        : stop.tone === "impacted" || stop.tone === "delivered"
          ? "ORIGINAL"
          : "REVISED",
  }));
}
