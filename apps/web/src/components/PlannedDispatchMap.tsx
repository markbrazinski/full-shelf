// =====================================================================
// Full Shelf — Google planned-dispatch map
// ---------------------------------------------------------------------
// A PLANNED-ROUTE visualization, never evidence of a live truck.
//
// The backend supplies what is planned: stop order, order IDs, cases,
// assignment, revision, capacity. Coordinates come from the documented
// DEMO_TENANT_LOCATION_REFERENCE directory — location configuration, not
// telemetry. Nothing here renders a position, bearing, heading, speed,
// or "last reported" time, and no marker moves.
//
// If the Maps key is absent or the API fails to load, the caller renders
// the existing SVG dispatch schematic instead of a blank panel.
// =====================================================================

import { useEffect, useRef, useState } from "react";
import { css } from "../styles/css";
import { DEMO_TENANT_LOCATIONS, locationFor, type ReferenceLocation } from "../data/contract/locations";

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

function loadMapsApi(apiKey: string): Promise<void> {
  const g = globalThis as MapsNamespace;
  if (g.google?.maps) return Promise.resolve();
  if (loaderPromise) return loaderPromise;

  loaderPromise = new Promise<void>((resolve, reject) => {
    // A rejected or unauthorized key does NOT trigger script.onerror —
    // Google loads the script, then calls gm_authFailure. Without this
    // hook an invalid key leaves an empty grey box instead of falling
    // back to the schematic.
    (globalThis as any).gm_authFailure = () => reject(new Error("Google Maps rejected the API key"));

    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&v=weekly`;
    script.async = true;
    script.onload = () => {
      // onload fires before auth is validated; confirm the API is usable.
      const ns = (globalThis as MapsNamespace).google?.maps;
      if (ns && typeof ns.Map === "function") resolve();
      else reject(new Error("Google Maps loaded without a usable API"));
    };
    script.onerror = () => reject(new Error("Google Maps failed to load"));
    document.head.appendChild(script);
    // A wedged network must fall back rather than hang the panel.
    setTimeout(() => reject(new Error("Google Maps load timed out")), 8_000);
  }).catch((e) => {
    loaderPromise = null;
    throw e;
  });
  return loaderPromise;
}

export function PlannedDispatchMap({ stops, label, apiKey, onFailure }: PlannedDispatchMapProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const painted = useRef(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    loadMapsApi(apiKey)
      .then(() => {
        if (cancelled || !ref.current) return;
        const maps = (globalThis as MapsNamespace).google?.maps;
        if (!maps) throw new Error("Google Maps namespace unavailable");
        const hub = locationFor("HUB")!;

        const map = new maps.Map(ref.current, {
          center: { lat: hub.lat, lng: hub.lng },
          zoom: 11,
          disableDefaultUI: true,
          zoomControl: true,
          clickableIcons: false,
        });

        const bounds = new maps.LatLngBounds();

        // Hub marker.
        new maps.Marker({
          map,
          position: { lat: hub.lat, lng: hub.lng },
          title: hub.label,
          label: { text: "H", color: "#ffffff", fontSize: "12px", fontWeight: "700" },
          icon: {
            path: maps.SymbolPath.CIRCLE,
            scale: 13,
            fillColor: "#16323b",
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 2,
          },
        });
        bounds.extend({ lat: hub.lat, lng: hub.lng });

        // One numbered marker per planned stop, plus a hub→facility path.
        const drawn = new Set<string>();
        for (const stop of stops) {
          const loc: ReferenceLocation | undefined =
            locationFor(stop.kind === "PARTNER" ? "STAGING" : stop.agency) ?? locationFor(stop.agency);
          if (!loc) continue; // no configured location → draw nothing, invent nothing

          const style = STYLE[stop.kind];
          const pos = { lat: loc.lat, lng: loc.lng };

          new maps.Marker({
            map,
            position: pos,
            title: `${stop.orderId} · ${stop.agency ?? loc.label}${stop.cases != null ? ` · ${stop.cases} cases` : ""}`,
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

          const key = `${stop.kind}:${loc.key}`;
          if (!drawn.has(key)) {
            drawn.add(key);
            // Planned, not travelled. The superseded original plan is a
            // muted solid line; live plans are dashed to read as intent.
            const dashed = stop.kind !== "ORIGINAL";
            new maps.Polyline({
              map,
              path: [{ lat: hub.lat, lng: hub.lng }, pos],
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
        const el = ref.current;
        maps.event.addListenerOnce(map, "tilesloaded", () => {
          painted.current = true;
        });
        window.setTimeout(() => {
          if (cancelled || painted.current) return;
          const hasTiles = !!el && el.querySelectorAll("img, canvas").length > 0;
          if (!hasTiles) {
            setFailed(true);
            onFailure();
          }
        }, 3_500);
      })
      .catch(() => {
        if (cancelled) return;
        setFailed(true);
        onFailure();
      });

    return () => {
      cancelled = true;
    };
  }, [apiKey, stops, onFailure]);

  if (failed) return null;

  return (
    <div>
      <div
        ref={ref}
        data-testid="planned-dispatch-map"
        style={css("width:100%;height:460px;border-radius:9px;border:1px solid #dbe1dc;background:#e7ebe7")}
      />
      <div style={css("display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:9px")}>
        {(Object.keys(STYLE) as (keyof typeof STYLE)[]).map((k) => (
          <span key={k} style={css("display:flex;align-items:center;gap:6px;font-size:11px;color:#43555c")}>
            <span style={css(`width:14px;height:3px;border-radius:2px;background:${STYLE[k].stroke}`)} />
            {STYLE[k].label}
          </span>
        ))}
        <span className="mono" data-testid="map-provenance-label" style={css("margin-left:auto;font-size:11px;color:#a85f12;letter-spacing:.02em")}>
          {label}
        </span>
      </div>
      <div className="mono" style={css("font-size:10px;color:#93a1a6;margin-top:5px;letter-spacing:.02em")}>
        Facility coordinates are DEMO_TENANT_LOCATION_REFERENCE configuration for {DEMO_TENANT_LOCATIONS.length} sites — not GPS, positions, or bearings.
      </div>
    </div>
  );
}
