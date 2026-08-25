// =====================================================================
// Full Shelf — HTTP projection data sources
// ---------------------------------------------------------------------
// Replay and live differ ONLY in base URL, credentials, and the data
// mode they are allowed to report. They share one fetch, one validator,
// and one normalizer so replay cannot drift from live behaviour.
// =====================================================================

import type { BeatId, DataMode, FullShelfProjection } from "../types/fullShelf";
import type { FullShelfDataSource, RepairApprovalRequest } from "./FullShelfDataSource";
import { boundaryFor } from "./contract/beats";
import { normalize } from "./contract/normalize";
import { ContractViolation, validateProjection } from "./contract/validate";

const PROJECTION_PATH = "/api/v1/projections/demo-beats";
const PROJECTION_STREAM_PATH = "/api/v1/projections/stream";
// The existing verified-human approval route. There is deliberately no
// second approval surface: one authority path, one place to audit.
const APPROVAL_PATH = "/api/v1/orchestrator/approvals/approve-and-activate";

/** POST the approval and surface any rejection verbatim. */
async function postApproval(
  request: RepairApprovalRequest,
  opts: Options,
): Promise<void> {
  const url = new URL(APPROVAL_PATH, opts.baseUrl);
  let res: Response;
  try {
    res = await fetch(url.toString(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(opts.authToken ? { Authorization: `Bearer ${opts.authToken}` } : {}),
      },
      credentials: opts.credentials ?? "omit",
      // Identity is derived from the proposal, so a browser cannot approve
      // a diff the agents never proposed. The orchestrator re-verifies the
      // operator token and the ledger re-signs the diff independently.
      body: JSON.stringify({
        command_id: `CMD-APPROVE-${request.proposalId}`.slice(0, 48),
        idempotency_key:
          `${request.tenantId}:${request.planId}:${request.proposedRevision}:approve`,
        tenant_id: request.tenantId,
        operating_day: request.operatingDay,
        incident_id: request.incidentId,
        plan_id: request.planId,
        source_revision: request.sourceRevision,
        proposed_revision: request.proposedRevision,
        approval_id: `APR-${request.proposedRevision}`,
        expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
        plan_diff: {
          reroute_order_id: request.planDiff.rerouteOrderId,
          reroute_cases: request.planDiff.rerouteCases,
          reroute_target_vehicle: request.planDiff.rerouteTargetVehicle,
          pickup_order_id: request.planDiff.pickupOrderId,
          pickup_cases: request.planDiff.pickupCases,
        },
      }),
    });
  } catch (e) {
    throw new ProjectionUnavailable(
      `Cannot reach the approval service at ${opts.baseUrl}. Nothing was committed.`,
      e,
    );
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body?.detail) detail = typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body; the status is enough */
    }
    throw new ProjectionUnavailable(`Approval rejected: ${detail}`);
  }
}

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

  approveRepair(request: RepairApprovalRequest): Promise<void> {
    return postApproval(request, { baseUrl: this.baseUrl, credentials: "omit" });
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

  subscribeToProjectionUpdates(
    onUpdate: () => void,
    onError: (error: unknown) => void,
  ): () => void {
    const controller = new AbortController();
    const url = new URL(PROJECTION_STREAM_PATH, this.baseUrl);
    void (async () => {
      try {
        const response = await fetch(url.toString(), {
          headers: {
            Accept: "text/event-stream",
            ...(this.authToken ? { Authorization: `Bearer ${this.authToken}` } : {}),
          },
          credentials: "include",
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new ProjectionUnavailable(`Projection stream rejected: HTTP ${response.status}`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!controller.signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let boundary = buffer.indexOf("\n\n");
          while (boundary >= 0) {
            const frame = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const event = frame.split("\n").find((line) => line.startsWith("event: "));
            const data = frame.split("\n").find((line) => line.startsWith("data: "));
            if (event === "event: projection_update" && data) {
              const payload = JSON.parse(data.slice(6)) as Record<string, unknown>;
              if (
                Object.keys(payload).length !== 1 ||
                typeof payload.receipt_cursor !== "string"
              ) {
                throw new ContractViolation("$.receipt_cursor", "cursor-only SSE payload required");
              }
              onUpdate();
            }
            boundary = buffer.indexOf("\n\n");
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) onError(error);
      }
    })();
    return () => controller.abort();
  }

  approveRepair(request: RepairApprovalRequest): Promise<void> {
    return postApproval(request, {
      baseUrl: this.baseUrl,
      credentials: "include",
      authToken: this.authToken,
    });
  }
}

export { ContractViolation };
