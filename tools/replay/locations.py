"""Configured East Bay reference locations for the deterministic runtime.

These are immutable build-time constants. The replay runtime performs no
geocoding and calls no Google service; coordinates were resolved once against
OpenStreetMap Nominatim and are recorded here with their provenance so any
reviewer can re-check them.

Display names are SYNTHETIC facility names for a deterministic demonstration.
Every entry carries location_mode CONFIGURED_REFERENCE and live_gps false. No
live GPS, tracking, or affiliation with any real organization is claimed. The
coordinates are plausible East Bay geography only.
"""

DISCLOSURE = (
    "Configured East Bay reference locations for deterministic demonstration. "
    "No live GPS or operational affiliation is claimed."
)

LOCATION_MODE = "CONFIGURED_REFERENCE"
GEOCODE_SOURCE = "OpenStreetMap Nominatim"
GEOCODE_SOURCE_URL = "https://nominatim.openstreetmap.org/"
GEOCODE_LICENSE = "© OpenStreetMap contributors, ODbL"
GEOCODE_RESOLVED_ON = "2026-08-25"

# match_quality records how precisely the geocoder resolved each coordinate,
# retained so a reviewer can see the provenance of the geography. Display names
# are synthetic and are NOT what was geocoded.
#   ORGANIZATION_MATCH - the query resolved to a named site
#   ADDRESS_MATCH      - the query resolved to a street address only
REFERENCE_LOCATIONS = (
    {
        "location_id": "FS-LOC-ACCFB",
        "display_name": "Bay Harvest Food Bank",
        "street_address": "1 Harvest Way, Oakland, CA",
        "latitude": 37.741645,
        "longitude": -122.201189,
        "role": "HUB",
        "custody_node_id": "N-WH",
        "agency_id": None,
        "order_ids": [],
        "location_mode": LOCATION_MODE,
        "live_gps": False,
        "source_url": "https://nominatim.openstreetmap.org/ui/details.html?place_id=323047356",
        "osm_place_id": 323047356,
        "match_quality": "ORGANIZATION_MATCH",
    },
    {
        "location_id": "FS-LOC-BFN",
        "display_name": "Berkeley Community Pantry",
        "street_address": "200 Shattuck Commons, Berkeley, CA",
        "latitude": 37.869016,
        "longitude": -122.294151,
        "role": "AGENCY",
        "custody_node_id": "N-AG01",
        "agency_id": "AGENCY-01",
        "order_ids": ["O201"],
        "location_mode": LOCATION_MODE,
        "live_gps": False,
        "source_url": "https://nominatim.openstreetmap.org/ui/details.html?place_id=323245378",
        "osm_place_id": 323245378,
        "match_quality": "ORGANIZATION_MATCH",
    },
    {
        "location_id": "FS-LOC-AFB",
        "display_name": "Alameda Family Pantry",
        "street_address": "45 Marina Court, Alameda, CA",
        "latitude": 37.784686,
        "longitude": -122.299163,
        "role": "AGENCY",
        "custody_node_id": "N-TR2",
        "agency_id": "AGENCY-02",
        "order_ids": ["O202"],
        "location_mode": LOCATION_MODE,
        "live_gps": False,
        "source_url": "https://nominatim.openstreetmap.org/ui/details.html?place_id=384377492",
        "osm_place_id": 384377492,
        "match_quality": "ADDRESS_MATCH",
    },
    {
        "location_id": "FS-LOC-SLCFP",
        "display_name": "East Oakland Community Pantry",
        "street_address": "3100 Foothill Commons, Oakland, CA",
        "latitude": 37.712594,
        "longitude": -122.137318,
        "role": "AGENCY",
        "custody_node_id": "N-STG",
        "agency_id": "AGENCY-03",
        "order_ids": ["O203"],
        "location_mode": LOCATION_MODE,
        "live_gps": False,
        "source_url": "https://nominatim.openstreetmap.org/ui/details.html?place_id=326077608",
        "osm_place_id": 326077608,
        "match_quality": "ORGANIZATION_MATCH",
    },
    {
        "location_id": "FS-LOC-PHFS",
        "display_name": "Hayward Neighborhood Food Center",
        "street_address": "820 Mission Court, Hayward, CA",
        "latitude": 37.674445,
        "longitude": -122.082600,
        "role": "AGENCY",
        "custody_node_id": "N-ST01",
        "agency_id": "AGENCY-04",
        "order_ids": ["O204"],
        "location_mode": LOCATION_MODE,
        "live_gps": False,
        "source_url": "https://nominatim.openstreetmap.org/ui/details.html?place_id=324159709",
        "osm_place_id": 324159709,
        "match_quality": "ADDRESS_MATCH",
    },
    {
        "location_id": "FS-LOC-TCV",
        "display_name": "Fremont Family Pantry",
        "street_address": "500 Mission Creek Way, Fremont, CA",
        "latitude": 37.555890,
        "longitude": -122.007661,
        "role": "AGENCY",
        "custody_node_id": "N-RESC",
        "agency_id": "AGENCY-05",
        "order_ids": ["O205"],
        "location_mode": LOCATION_MODE,
        "live_gps": False,
        "source_url": "https://nominatim.openstreetmap.org/ui/details.html?place_id=324088547",
        "osm_place_id": 324088547,
        "match_quality": "ORGANIZATION_MATCH",
    },
)

# Bay Area sanity envelope. A coordinate outside this is a configuration error.
BAY_AREA_BOUNDS = {"min_lat": 37.4, "max_lat": 38.1,
                   "min_lon": -122.6, "max_lon": -121.9}


def reference_locations():
    """Immutable configured reference locations, stable across every session."""
    return {
        "classification": "SYNTHETIC_TEST",
        "location_mode": LOCATION_MODE,
        "live_gps": False,
        "disclosure": DISCLOSURE,
        "geocode_source": GEOCODE_SOURCE,
        "geocode_source_url": GEOCODE_SOURCE_URL,
        "geocode_license": GEOCODE_LICENSE,
        "geocode_resolved_on": GEOCODE_RESOLVED_ON,
        "locations": [dict(entry) for entry in REFERENCE_LOCATIONS],
    }
