"""One-time generator for CONFIGURED_REFERENCE route geometry.

Run manually. NEVER called at capture time, by the app, or by any test.

Fetches road-following geometry once from the public OSRM demo server
(OpenStreetMap data) for the canonical vehicle legs and writes the
coordinates to apps/web/src/data/contract/referenceRoutes.json.

What is committed is COORDINATES ONLY. No ETA, distance, duration, or
travel claim is retained: the geometry states which roads a planned route
would follow, never that any vehicle drove it. It calls no Google service
and needs no credential.

    .venv/bin/python scripts/fetch_reference_routes.py
"""

import json
import pathlib
import sys
import urllib.request

OSRM = "https://router.project-osrm.org/route/v1/driving/"
OUT = (pathlib.Path(__file__).resolve().parent.parent
       / "apps/web/src/data/contract/referenceRoutes.json")

# Coordinates are the runtime's own configured reference locations
# (tools/replay/locations.py). Kept in sync by ROUTE definitions below.
HUB = (37.741645, -122.201189)
BERKELEY = (37.869016, -122.294151)
ALAMEDA = (37.784686, -122.299163)
EAST_OAKLAND = (37.712594, -122.137318)
HAYWARD = (37.674445, -122.082600)
FREMONT = (37.555890, -122.007661)

# Canonical planned legs. Every route starts and ends at the hub.
ROUTES = {
    # rev07 Truck 1: hub -> Berkeley -> Alameda -> East Oakland -> hub
    "T1_REV07": [HUB, BERKELEY, ALAMEDA, EAST_OAKLAND, HUB],
    # rev07 Truck 2: hub -> Hayward -> Fremont -> hub
    "T2_REV07": [HUB, HAYWARD, FREMONT, HUB],
    # rev08 Truck 2 absorbs O202 (Alameda): hub -> Alameda -> Hayward -> Fremont -> hub
    "T2_REV08": [HUB, ALAMEDA, HAYWARD, FREMONT, HUB],
    # rev08 partner fulfilment of O203 (East Oakland), hub round trip
    "PARTNER_REV08": [HUB, EAST_OAKLAND, HUB],
    # Saturday candidate: hub -> Berkeley -> Alameda -> hub
    "T2_SATURDAY": [HUB, BERKELEY, ALAMEDA, HUB],
}


def fetch(points):
    """Road-following coordinates for one ordered set of waypoints."""
    coords = ";".join(f"{lon},{lat}" for lat, lon in points)
    url = f"{OSRM}{coords}?overview=full&geometries=geojson"
    with urllib.request.urlopen(url, timeout=60) as response:
        body = json.load(response)
    if body.get("code") != "Ok":
        raise SystemExit(f"OSRM refused: {body.get('code')} {body.get('message', '')}")
    line = body["routes"][0]["geometry"]["coordinates"]
    # GeoJSON is [lon, lat]; store [lat, lng] rounded to ~1m for a stable diff.
    return [[round(lat, 5), round(lon, 5)] for lon, lat in line]


def main():
    out = {
        "classification": "CONFIGURED_REFERENCE_ROUTE",
        "note": (
            "Road-following geometry for planned reference routes between "
            "configured facilities. Not a travelled route, not live GPS, and "
            "not evidence that any vehicle moved. No ETA, distance, or "
            "duration is retained."
        ),
        "attribution": "Route geometry © OpenStreetMap contributors",
        "source": "OSRM (router.project-osrm.org), OpenStreetMap data",
        "license": "ODbL",
        "routes": {},
    }
    for name, points in ROUTES.items():
        line = fetch(points)
        out["routes"][name] = line
        print(f"{name}: {len(line)} coordinates", file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
