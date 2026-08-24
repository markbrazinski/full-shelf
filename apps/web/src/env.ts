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
import { LiveOrchestratorDataSource, ReplayHttpDataSource } from "./data/ProjectionHttpDataSource";

const DEFAULT_REPLAY_URL = "http://127.0.0.1:8787";

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
  const kind = resolveDataSourceKind();
  const url = resolveOrchestratorUrl(kind);
  return kind === "live"
    ? new LiveOrchestratorDataSource(url)
    : new ReplayHttpDataSource(url);
}

/** Browser Maps key. Absent is normal: the SVG schematic is the fallback. */
export function googleMapsApiKey(): string | undefined {
  const k = import.meta.env.VITE_GOOGLE_MAPS_API_KEY?.trim();
  return k ? k : undefined;
}

export function isReplayMode(): boolean {
  return resolveDataSourceKind() === "deterministic_replay";
}
