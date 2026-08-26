// =====================================================================
// Full Shelf — Google planned-dispatch map
// ---------------------------------------------------------------------
// A CONFIGURED-REFERENCE visualization, never evidence of a live truck.
//
// Coordinates come from the runtime's own `reference_locations` — six
// configured East Bay sites resolved once at build time, carried on every
// projection, and identical across sessions and resets. The runtime
// performs no geocoding and calls no Google service; this component reads
// what the projection supplies and invents nothing.
//
// Nothing here renders a position, bearing, heading, speed, moving truck,
// driven route, or "last reported" time. No route geometry exists at any
// cursor (`telemetry.position_available` is false throughout), so stops
// are placed as markers and connected to the hub by straight configured
// lines that read as assignment, never as travel.
//
// If the Maps key is absent or the API fails to load, the caller renders
// the SVG schematic instead of a blank panel.
// =====================================================================

import { useEffect, useRef, useState } from "react";
import { css } from "../styles/css";
import type { MapLocation } from "../types/fullShelf";

export interface PlannedStop {
  orderId: string;
  agency: string | null;
  cases: number | null;
  /** 1-based position in the planned sequence for this vehicle. */
  sequence: number;
  kind: "ORIGINAL" | "REVISED" | "PARTNER";
}

export interface PlannedDispatchMapProps {
  stops: PlannedStop[];
  /** The runtime's six configured reference locations. */
  locations: MapLocation[];
  /** The runtime's own disclosure text, rendered verbatim. */
  disclosure?: string;
  label: string;
  apiKey: string;
  onFailure: () => void;
}

// Planned-path styling. Colors carry plan intent, never live status.
const STYLE = {
  ORIGINAL: { stroke: "#a23b2b", fill: "#a23b2b", label: "Original Truck 1 plan" },
  REVISED: { stroke: "#1f6f8b", fill: "#1f6f8b", label: "Revised Truck 2 plan" },
  PARTNER: { stroke: "#a85f12", fill: "#a85f12", label: "Partner pickup" },
} as const;

type MapsNamespace = typeof globalThis & { google?: any };

let loaderPromise: Promise<void> | null = null;

/**
 * Load the Maps JavaScript API and resolve only once it is genuinely
 * usable.
 *
 * With `loading=async` the bootstrap loader fires `script.onload` BEFORE
 * `google.maps` is populated, so checking the namespace there always
 * throws. The supported path is `google.maps.importLibrary`, which the
 * bootstrap defines synchronously and which resolves when the library is
 * actually ready.
 */
function loadMapsApi(apiKey: string): Promise<void> {
  const g = globalThis as MapsNamespace;
  if (g.google?.maps?.Map) return Promise.resolve();
  if (loaderPromise) return loaderPromise;

  loaderPromise = new Promise<void>((resolve, reject) => {
    // A rejected or unauthorized key does NOT trigger script.onerror —
    // Google loads the script, then calls gm_authFailure. Without this
    // hook an invalid key leaves an empty grey box instead of falling
    // back to the schematic.
    (globalThis as any).gm_authFailure = () =>
      reject(new Error("Google Maps rejected the API key"));

    const script = document.createElement("script");
    script.src =
      `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}` +
      "&v=weekly&loading=async&libraries=maps,marker&callback=__fsMapsReady";
    script.async = true;

    // The bootstrap invokes this once `google.maps` is populated.
    (globalThis as any).__fsMapsReady = () => {
      const ns = (globalThis as MapsNamespace).google?.maps;
      if (ns && typeof ns.Map === "function") resolve();
      else reject(new Error("Google Maps loaded without a usable API"));
    };

    script.onerror = () => reject(new Error("Google Maps failed to load"));
    document.head.appendChild(script);

    // A wedged network must fall back rather than hang the panel. A
    // settled promise ignores this, so a slow-but-successful load is
    // never turned into a failure.
    setTimeout(() => reject(new Error("Google Maps load timed out")), 8_000);
  }).catch((e) => {
    loaderPromise = null;
    throw e;
  });
  return loaderPromise;
}

/**
 * Resolve a stop to one of the runtime's configured locations.
 *
 * The projection binds each location to its agency and orders, so the
 * match is on projected identity — never on a coordinate guessed from a
 * display string. A stop with no configured location draws nothing.
 */
function locationForStop(stop: PlannedStop, locations: MapLocation[]): MapLocation | undefined {
  const byOrder = locations.find((l) => l.orderIds?.includes(stop.orderId));
  if (byOrder) return byOrder;
  if (!stop.agency) return undefined;
  // "Agency 02" → AGENCY-02, the runtime's own agency_id spelling.
  const agencyId = stop.agency.trim().toUpperCase().replace(/\s+/g, "-");
  return locations.find((l) => l.agencyId === agencyId);
}

export function PlannedDispatchMap({
  stops,
  locations,
  disclosure,
  label,
  apiKey,
  onFailure,
}: PlannedDispatchMapProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const painted = useRef(false);
  const [failed, setFailed] = useState(false);

  // The projection is re-read after every committed event, so `stops` and
  // `locations` arrive as fresh array identities roughly once a second.
  // Keying the effect on those references tore the map down and rebuilt
  // it mid-load on every frame, so it never survived long enough to paint.
  // Key on the CONTENT that actually changes the drawing instead.
  const stopsKey = stops.map((s) => `${s.orderId}:${s.kind}:${s.sequence}`).join("|");
  const locationsKey = locations.map((l) => l.id).join("|");

  useEffect(() => {
    let cancelled = false;
    const hub = locations.find((l) => l.role === "HUB") ?? locations[0];
    if (!hub) return; // nothing configured → draw nothing, invent nothing

    loadMapsApi(apiKey)
      .then(() => {
        if (cancelled || !ref.current) return;
        const maps = (globalThis as MapsNamespace).google?.maps;
        if (!maps) throw new Error("Google Maps namespace unavailable");

        const map = new maps.Map(ref.current, {
          center: { lat: hub.lat, lng: hub.lon },
          zoom: 11,
          disableDefaultUI: true,
          zoomControl: true,
          clickableIcons: false,
        });

        const bounds = new maps.LatLngBounds();

        // Every configured reference location is drawn, whether or not a
        // stop currently references it: the six sites are the tenant's
        // configured geography, not a function of today's manifest.
        for (const loc of locations) {
          const isHub = loc.role === "HUB";
          new maps.Marker({
            map,
            position: { lat: loc.lat, lng: loc.lon },
            title: `${loc.name}${loc.address ? ` · ${loc.address}` : ""} · configured reference location`,
            label: isHub
              ? { text: "H", color: "#ffffff", fontSize: "12px", fontWeight: "700" }
              : undefined,
            icon: {
              path: maps.SymbolPath.CIRCLE,
              scale: isHub ? 13 : 8,
              fillColor: isHub ? "#16323b" : "#7d8d92",
              fillOpacity: 1,
              strokeColor: "#ffffff",
              strokeWeight: 2,
            },
          });
          bounds.extend({ lat: loc.lat, lng: loc.lon });
        }

        // One numbered marker per planned stop, over its configured site,
        // plus a hub→site line. The line is a configured connection, not a
        // driven route: no route geometry exists at any cursor.
        const drawn = new Set<string>();
        for (const stop of stops) {
          const loc = locationForStop(stop, locations);
          if (!loc) continue;

          const style = STYLE[stop.kind];
          const pos = { lat: loc.lat, lng: loc.lon };

          new maps.Marker({
            map,
            position: pos,
            title: `${stop.orderId} · ${loc.name}${stop.cases != null ? ` · ${stop.cases} cases` : ""}`,
            label: { text: String(stop.sequence), color: "#ffffff", fontSize: "11px", fontWeight: "700" },
            icon: {
              path: maps.SymbolPath.CIRCLE,
              scale: 11,
              fillColor: style.fill,
              fillOpacity: 1,
              strokeColor: "#ffffff",
              strokeWeight: 2,
            },
          });

          const key = `${stop.kind}:${loc.id}`;
          if (!drawn.has(key)) {
            drawn.add(key);
            // Configured connection, not travelled. The superseded original
            // plan is a muted solid line; live plans are dashed as intent.
            const dashed = stop.kind !== "ORIGINAL";
            new maps.Polyline({
              map,
              path: [{ lat: hub.lat, lng: hub.lon }, pos],
              strokeColor: style.stroke,
              strokeOpacity: dashed ? 0 : 0.45,
              strokeWeight: dashed ? 4 : 3,
              icons: dashed
                ? [
                    {
                      icon: { path: "M 0,-1 0,1", strokeOpacity: 0.9, strokeWeight: 4, scale: 3, strokeColor: style.stroke },
                      offset: "0",
                      repeat: "14px",
                    },
                  ]
                : undefined,
            });
          }
          bounds.extend(pos);
        }

        if (!bounds.isEmpty()) map.fitBounds(bounds, 56);

        // An unauthorized key can load the API yet render nothing, which
        // would leave an empty grey panel. Confirm the map actually
        // painted tiles; if it did not, fall back to the schematic.
        maps.event.addListenerOnce(map, "tilesloaded", () => {
          painted.current = true;
        });
        window.setTimeout(() => {
          if (cancelled || painted.current) return;
          // Only the Maps `tilesloaded` event establishes a painted basemap.
          // Overlay marker images must never make a tile-less map look valid.
          setFailed(true);
          onFailure();
        }, 3_500);
      })
      .catch(() => {
        if (cancelled) return;
        // A degraded Maps runtime costs us the map, never the page.
        setFailed(true);
        onFailure();
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, stopsKey, locationsKey]);

  if (failed) return null;

  return (
    <div>
      <div
        ref={ref}
        data-testid="planned-dispatch-map"
        style={css("width:100%;height:410px;border-radius:9px;border:1px solid #dbe1dc;background:#e7ebe7")}
      />
      <div style={css("display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:9px")}>
        {(Object.keys(STYLE) as (keyof typeof STYLE)[]).map((k) => (
          <span key={k} style={css("display:flex;align-items:center;gap:6px;font-size:11px;color:#43555c")}>
            <span style={css(`width:14px;height:3px;border-radius:2px;background:${STYLE[k].stroke}`)} />
            {STYLE[k].label}
          </span>
        ))}
        <span className="mono" data-testid="map-provenance-label" style={css("margin-left:auto;font-size:10px;color:#a85f12;letter-spacing:.02em;font-weight:600")}>
          ◆ {label}
        </span>
      </div>
      <div
        className="mono"
        data-testid="map-location-disclosure"
        style={css("font-size:10px;color:#93a1a6;margin-top:5px;letter-spacing:.02em;line-height:1.5")}
      >
        {locations.length} configured reference locations · no live GPS
        {disclosure ? ` — ${disclosure}` : ""}
      </div>
    </div>
  );
}
