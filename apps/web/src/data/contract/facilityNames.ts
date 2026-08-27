// =====================================================================
// Full Shelf — facility display names
// ---------------------------------------------------------------------
// ONE place that turns an authoritative identifier into the operator-
// facing facility name, so maps, manifests, custody, recovery, Saturday,
// Fleet Activity, History and the Execution Record all say the same
// thing about the same place.
//
// This is a DISPLAY mapping over identifiers the runtime already emits.
// It invents no facility and changes no quantity: the identifier stays
// authoritative and is kept alongside the name as secondary metadata.
// An unknown identifier resolves to itself rather than to a guess.
// =====================================================================

/**
 * Authoritative identifier → operator-facing facility name.
 *
 * Keys cover every spelling the runtime uses for the same place:
 * agency ids (`AGENCY-01`), commitment agency labels (`Agency 01`) and
 * custody node ids (`N-AG01`).
 */
const FACILITY_NAMES: Record<string, string> = {
  // Hub
  "HUB": "Bay Harvest Food Bank",
  "N-WH": "Bay Harvest Food Bank",

  // Agencies
  "AGENCY-01": "Berkeley Community Pantry",
  "AGENCY 01": "Berkeley Community Pantry",
  "N-AG01": "Berkeley Community Pantry",

  "AGENCY-02": "Alameda Family Pantry",
  "AGENCY 02": "Alameda Family Pantry",
  "N-AG02": "Alameda Family Pantry",

  "AGENCY-03": "East Oakland Community Pantry",
  "AGENCY 03": "East Oakland Community Pantry",
  "N-AG03": "East Oakland Community Pantry",

  "AGENCY-04": "Hayward Neighborhood Food Center",
  "AGENCY 04": "Hayward Neighborhood Food Center",

  "AGENCY-05": "Fremont Family Pantry",
  "AGENCY 05": "Fremont Family Pantry",

  // Downstream site — the eight unconfirmed cases live here.
  "SITE-01": "East Bay Distribution Annex",
  "SITE 01": "East Bay Distribution Annex",
  "N-ST01": "East Bay Distribution Annex",

  // Refrigerated partner carrier for O203.
  "PARTNER": "Tri-City Cold Storage",
  "PARTNER_PICKUP": "Tri-City Cold Storage",
  "N-STG": "Tri-City Cold Storage",
};

/**
 * The operator-facing name for an authoritative identifier.
 *
 * Returns the identifier unchanged when nothing is configured for it, so
 * an unmapped place is shown honestly rather than renamed by guesswork.
 */
export function facilityName(id: string | null | undefined): string {
  if (!id) return "";
  const key = id.trim().toUpperCase();
  return FACILITY_NAMES[key] ?? id;
}

/** True when `id` has a configured operator-facing name. */
export function hasFacilityName(id: string | null | undefined): boolean {
  if (!id) return false;
  return FACILITY_NAMES[id.trim().toUpperCase()] !== undefined;
}
