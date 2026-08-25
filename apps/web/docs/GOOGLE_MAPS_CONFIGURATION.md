# Google Maps browser configuration

Full Shelf uses only the Google Maps JavaScript API to draw a basemap under
projection-derived planned stops and deterministic simulated telemetry. The
browser key is supplied at build time as `VITE_GOOGLE_MAPS_API_KEY`; it must
never be committed to Git or placed in a checked-in `.env` file.

The key is a browser identifier and will appear in the built JavaScript request.
Before any production build receives it, configure both restrictions in Google
Cloud Console:

1. Application restriction: **Websites (HTTP referrers)**.
2. Add only the exact HTTPS origin that serves this Vite application, expressed
   as `https://<approved-production-host>/*`. Add each approved preview origin
   explicitly; do not authorize `*`, a wildcard top-level domain, the
   orchestrator origin, or localhost on the production key.
3. API restriction: **Restrict key**, with only **Maps JavaScript API** selected.
   Full Shelf does not use Places, Directions, Routes, Geocoding, or a Maps web
   service.
4. The loader sends `auth_referrer_policy=origin`, so Cloud Console restrictions
   must match the origin without a path-specific rule.

The production frontend hostname is not defined in this repository. Release is
therefore blocked from receiving a production Maps key until release authority
records that exact origin and applies the restriction. A separate development
key may allow only the explicit loopback origin used for local filming, such as
`http://127.0.0.1:5190/*`.

If the key is absent, rejected, the loader fails, or base-map tiles do not paint,
the UI automatically replaces the map with the deterministic schematic. Both
paths retain the ordered manifests and label positions as simulated—not live
GPS. Deterministic replay makes no Gemini, ADK, Model Armor, KMS, Spanner, or
other managed-service request.

References:

- <https://developers.google.com/maps/api-security-best-practices>
- <https://developers.google.com/maps/documentation/javascript/load-maps-js-api>
