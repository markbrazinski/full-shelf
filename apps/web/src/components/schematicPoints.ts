// =====================================================================
// Full Shelf — configured-coordinate schematic projection
// ---------------------------------------------------------------------
// Projects the runtime's own latitude/longitude onto a 0..100 panel box
// so the schematic fallback draws the SAME six configured sites the
// Google map does. It is a relative-position drawing of real configured
// coordinates, never an invented city layout.
// =====================================================================

import type { MapLocation } from "../types/fullShelf";

export function schematicPoints(locations: MapLocation[]): Map<string, [number, number]> {
  const pts = new Map<string, [number, number]>();
  if (!locations.length) return pts;

  const lats = locations.map((l) => l.lat);
  const lons = locations.map((l) => l.lon);
  const [minLat, maxLat] = [Math.min(...lats), Math.max(...lats)];
  const [minLon, maxLon] = [Math.min(...lons), Math.max(...lons)];
  const spanLat = maxLat - minLat || 1;
  const spanLon = maxLon - minLon || 1;

  for (const l of locations) {
    // Inset so a marker at an extreme never clips its panel.
    const x = 14 + ((l.lon - minLon) / spanLon) * 72;
    const y = 12 + ((maxLat - l.lat) / spanLat) * 76;
    pts.set(l.id, [x, y]);
  }
  return pts;
}
