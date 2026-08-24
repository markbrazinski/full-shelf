// =====================================================================
// Full Shelf — planned stops for the dispatch map
// ---------------------------------------------------------------------
// Derives map stops from the normalized DispatchView. Classification is
// read from the stop's own tone, which the normalizer set from the
// contract's assignment_type/status — never guessed here.
//
// ORIGINAL = the superseded Truck 1 plan (muted/red)
// REVISED  = the active Truck 2 plan (blue)
// PARTNER  = refrigerated partner pickup (amber)
// =====================================================================

import type { DispatchView } from "../../types/fullShelf";
import type { PlannedStop } from "../../components/PlannedDispatchMap";

/** "1. O202 · Agency 02" → "Agency 02"; sub "22 cases · Truck 2" → 22. */
const AGENCY_RE = /·\s*(Agency\s*\d+)/;
const CASES_RE = /(\d+)\s*cases/;

export function plannedStopsFrom(dispatch: DispatchView): PlannedStop[] {
  const out: PlannedStop[] = [];
  let seq = 0;

  for (const [orderId, stop] of Object.entries(dispatch.stops)) {
    const agency = AGENCY_RE.exec(stop.title)?.[1] ?? null;
    const casesMatch = CASES_RE.exec(stop.sub);
    const cases = casesMatch ? Number(casesMatch[1]) : null;

    const kind: PlannedStop["kind"] =
      stop.tone === "partner"
        ? "PARTNER"
        : stop.tone === "impacted" || stop.tone === "delivered"
          ? "ORIGINAL"
          : "REVISED";

    seq += 1;
    out.push({ orderId, agency, cases, sequence: seq, kind });
  }
  return out;
}
