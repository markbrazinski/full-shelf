// =====================================================================
// Full Shelf — runtime data-source selection
// ---------------------------------------------------------------------
// The single place the runtime decides where truth comes from. The
// Design fixture is deliberately NOT reachable from here; it is
// reference material for tests and isolated component work only.
//
//   VITE_DATA_SOURCE=deterministic_replay   (localhost replay server)
//   VITE_DATA_SOURCE=live                   (deployed orchestrator)
// =====================================================================

import type { FullShelfDataSource } from "./data/FullShelfDataSource";
import { SessionBridgeDataSource } from "./data/SessionBridgeDataSource";

const DEFAULT_REPLAY_URL = "http://127.0.0.1:8788";

export type DataSourceKind = "deterministic_replay" | "live";

export function resolveDataSourceKind(): DataSourceKind {
  const raw = (import.meta.env.VITE_DATA_SOURCE ?? "deterministic_replay").trim();
  if (raw === "live") return "live";
  if (raw === "deterministic_replay") return "deterministic_replay";
  throw new Error(
    `VITE_DATA_SOURCE must be "deterministic_replay" or "live"; received "${raw}".`,
  );
}

export function resolveOrchestratorUrl(kind: DataSourceKind): string {
  const configured = import.meta.env.VITE_ORCHESTRATOR_URL?.trim();
  if (configured) return configured;
  if (kind === "deterministic_replay") return DEFAULT_REPLAY_URL;
  throw new Error("VITE_ORCHESTRATOR_URL is required when VITE_DATA_SOURCE=live.");
}

export function createDataSource(): FullShelfDataSource {
  // Golden Runtime Controller on 8788 (session-based)
  return new SessionBridgeDataSource();
}

/**
 * Browser Maps key. Absent is normal: the SVG schematic is the fallback.
 *
 * Verification may force a key so the invalid-key and unauthorized-key
 * fallback paths are genuinely exercised rather than passing merely
 * because no key was configured. It only ever supplies a FAKE key — a
 * real key is never read from, or written to, the page.
 */
export function googleMapsApiKey(): string | undefined {
  const forced = (globalThis as { __FS_FORCE_MAP_KEY?: string }).__FS_FORCE_MAP_KEY;
  if (forced) return forced;
  const k = import.meta.env.VITE_GOOGLE_MAPS_API_KEY?.trim();
  return k ? k : undefined;
}

export function isReplayMode(): boolean {
  return resolveDataSourceKind() === "deterministic_replay";
}

/**
 * Replay navigation is deliberately absent from the ordinary film canvas.
 * A developer can opt into the diagnostic controls only on a local Vite
 * development build with an explicit `?debug=1` query parameter.
 */
export function debugReplayControlsEnabled(): boolean {
  if (!import.meta.env.DEV || !isReplayMode() || typeof location === "undefined") return false;
  return new URLSearchParams(location.search).get("debug") === "1";
}
