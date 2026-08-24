// =====================================================================
// Full Shelf — HTTP projection data sources
// ---------------------------------------------------------------------
// Replay and live differ ONLY in base URL, credentials, and the data
// mode they are allowed to report. They share one fetch, one validator,
// and one normalizer so replay cannot drift from live behaviour.
// =====================================================================

import type { BeatId, DataMode, FullShelfProjection } from "../types/fullShelf";
import type { FullShelfDataSource } from "./FullShelfDataSource";
import { boundaryFor } from "./contract/beats";
import { normalize } from "./contract/normalize";
import { ContractViolation, validateProjection } from "./contract/validate";

const PROJECTION_PATH = "/api/v1/projections/demo-beats";

export class ProjectionUnavailable extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = "ProjectionUnavailable";
  }
}

interface Options {
  baseUrl: string;
  /** Overrides the classification-derived mode for live sources. */
  forceDataMode?: DataMode;
  /** Live deployments sit behind IAM; replay never sends credentials. */
  credentials?: RequestCredentials;
  authToken?: string;
}

async function fetchProjection(beatId: BeatId, opts: Options): Promise<FullShelfProjection> {
  const b = boundaryFor(beatId);
  const url = new URL(PROJECTION_PATH, opts.baseUrl);
  // as_of is ALWAYS explicit: a refresh must return identical truth.
  url.searchParams.set("as_of", b.asOf);
  // Tomorrow is only ever requested deliberately.
  if (b.includeNextDayDraft) url.searchParams.set("include_next_day_draft", "true");

  let res: Response;
  try {
    res = await fetch(url.toString(), {
      headers: {
        Accept: "application/json",
        ...(opts.authToken ? { Authorization: `Bearer ${opts.authToken}` } : {}),
      },
      credentials: opts.credentials ?? "omit",
    });
  } catch (e) {
    throw new ProjectionUnavailable(
      `Cannot reach the projection service at ${opts.baseUrl}. The view is not rendered rather than shown with stale or invented data.`,
      e,
    );
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body; the status is enough */
    }
    throw new ProjectionUnavailable(`Projection request rejected: ${detail}`);
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch (e) {
    throw new ProjectionUnavailable("Projection response was not valid JSON.", e);
  }

  // Trust boundary: validate before a single field is read.
  const raw = validateProjection(body);

  const projection = normalize(raw, beatId);
  if (opts.forceDataMode) projection.dataMode = opts.forceDataMode;
  return projection;
}

/**
 * Deterministic replay against the localhost fixture server
 * (tools/replay/server.py). Always SYNTHETIC_TEST.
 */
export class ReplayHttpDataSource implements FullShelfDataSource {
  constructor(private readonly baseUrl: string) {}

  getProjection(beatId: BeatId): Promise<FullShelfProjection> {
    return fetchProjection(beatId, {
      baseUrl: this.baseUrl,
      forceDataMode: "SYNTHETIC_TEST",
      credentials: "omit",
    });
  }
}

/**
 * Live orchestrator. Reports whatever classification the service
 * asserts; it must never be forced to SYNTHETIC_TEST.
 */
export class LiveOrchestratorDataSource implements FullShelfDataSource {
  constructor(private readonly baseUrl: string, private readonly authToken?: string) {}

  getProjection(beatId: BeatId): Promise<FullShelfProjection> {
    return fetchProjection(beatId, {
      baseUrl: this.baseUrl,
      credentials: "include",
      authToken: this.authToken,
    });
  }
}

export { ContractViolation };
