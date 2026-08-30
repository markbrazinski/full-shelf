// =====================================================================
// Golden Runtime Session Data Source
// =====================================================================
// Real session-lifecycle data source targeting the Golden Runtime
// Controller (tools/replay/runtime_server.py) on http://127.0.0.1:8788

import { normalize } from "./SessionNormalizer";
import type { FullShelfProjection } from "../types/fullShelf";

export interface SessionSnapshot {
  session_id: string;
  cursor: number;
}

export interface EventEnvelope {
  event_id: string;
  /** Canonical integer, or a `b`-prefixed branch ordinal. */
  sequence: number | string;
  effective_at: string;
  event_type: string;
  authority?: string;
  activity_entry: {
    severity: string;
    headline: string;
    detail: string;
    action_required: boolean;
  };
}

export interface AdvanceResult {
  ok: boolean;
  /**
   * The sequence the runtime actually committed, when it committed one.
   *
   * The runtime already returns the committed frame; reading it is what
   * lets a caller tell "this request moved the cursor" from "this request
   * was refused", without inferring it from a second read that could
   * itself race.
   */
  sequence?: number;
  status?: number;
  message?: string; // "HUMAN_APPROVAL_REQUIRED", "REPLAY_COMPLETE", "CANONICAL_ADVANCE_BLOCKED_IN_BRANCH"
}

export interface BranchResult {
  branch: "vague" | "complete";
  label: string;
  custody: { unique: number; confirmed: number; unconfirmed: number };
  domain_mutations: number;
  evidence_mutations: number;
  events: EventEnvelope[];
}

interface GoldenRuntimeConfig {
  baseUrl: string;
}

/**
 * Where the replay API lives.
 *
 * In the deployed judge build the frontend and the replay API are served
 * by one container, so the API is same-origin and the base URL is empty —
 * requests go to `/api/v1/replay/...` on whatever host served the page.
 * That is also what keeps the deployment free of any CORS grant.
 *
 * Local development is unchanged: Vite serves the page on 5173 while the
 * runtime controller listens on 8788, two different origins, so the
 * explicit loopback default still applies there.
 */
export function defaultRuntimeBaseUrl(): string {
  const configured = import.meta.env.VITE_REPLAY_API_BASE?.trim();
  if (configured !== undefined && configured !== "") {
    return configured === "same-origin" ? "" : configured;
  }
  return "http://127.0.0.1:8788";
}

/**
 * Recover from a session the server no longer holds.
 *
 * Replay sessions live in the serving instance's memory. Cloud Run keeps a
 * visitor pinned to one instance, but that is best-effort: an instance
 * recycling, or scaling activity, can leave a browser holding an id nobody
 * answers for, and every later call 404s.
 *
 * A lost session has nothing to salvage — it holds presentation state only,
 * and the replay always starts from the same committed opening event. So the
 * honest recovery is to start a clean one, which is exactly what a judge
 * pressing Restart would get. Reloading is what performs that, and it is
 * done once: a reload loop would be worse than the error it replaces.
 */
let recovering = false;
function recoverLostSession(): void {
  if (recovering || typeof location === "undefined") return;
  recovering = true;
  location.reload();
}

export class GoldenRuntimeDataSource {
  private config: GoldenRuntimeConfig;

  constructor(baseUrl = defaultRuntimeBaseUrl()) {
    this.config = { baseUrl };
  }

  async createSession(): Promise<SessionSnapshot> {
    const res = await fetch(`${this.config.baseUrl}/api/v1/replay/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: "test" }),
    });
    if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
    return await res.json();
  }

  async getProjection(sessionId: string, observedCursor?: number): Promise<FullShelfProjection> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/projection`
    );
    // The serving instance no longer holds this session. Start a clean one
    // rather than stranding the judge on a connection error.
    if (res.status === 404) recoverLostSession();
    if (!res.ok) throw new Error(`Failed to get projection: ${res.status}`);
    const raw = await res.json();
    return normalize(raw, observedCursor);
  }

  /** Session state: cursor, mode, approval gate, branch. */
  async getState(sessionId: string): Promise<{
    cursor: number;
    mode: string;
    approval_required: boolean;
    approved: boolean;
    branch: string | null;
  }> {
    const res = await fetch(`${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}`);
    if (!res.ok) throw new Error(`Failed to get state: ${res.status}`);
    return await res.json();
  }

  subscribe(
    sessionId: string,
    lastEventId: string | undefined,
    onEvent: (envelope: EventEnvelope) => void,
    onError: (err: Error) => void
  ): () => void {
    let aborted = false;
    // The highest canonical ordinal actually delivered. A reconnect
    // resumes strictly after it, so no committed event is missed and
    // none is replayed twice.
    let resumeFrom = lastEventId;

    (async () => {
      // A stream can end without the replay being over: the deployed
      // transport closes a caught-up stream after an idle period so an
      // abandoned tab stops holding a request slot. Ending is therefore
      // normal, and the client's job is to resume from its cursor rather
      // than to stall — which is exactly what the runtime's
      // `Last-Event-ID` handling already supports.
      for (let attempt = 0; !aborted; attempt++) {
        try {
          const headers: Record<string, string> = {
            Accept: "text/event-stream",
          };
          if (resumeFrom) {
            headers["Last-Event-ID"] = resumeFrom;
          }

          const res = await fetch(
            `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/stream`,
            { headers }
          );
          if (res.status === 404) {
            recoverLostSession();
            return;
          }
          if (!res.ok) throw new Error(`SSE failed: ${res.status}`);

          const reader = res.body?.getReader();
          if (!reader) throw new Error("No response body");

          const decoder = new TextDecoder();
          let buffer = "";

          while (!aborted) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const frames = buffer.split("\n\n");
            buffer = frames.pop() || "";

            for (const frame of frames) {
              if (!frame.trim()) continue;

              let data: string | undefined;

              for (const line of frame.split("\n")) {
                if (line.startsWith("data:")) data = line.slice(5).trim();
              }

              if (data) {
                try {
                  const envelope = JSON.parse(data) as EventEnvelope;
                  // Only canonical ordinals resume; branch ordinals are
                  // `b`-prefixed and belong to an isolated namespace.
                  const seq = Number(envelope.sequence);
                  if (Number.isFinite(seq)) resumeFrom = String(seq);
                  onEvent(envelope);
                } catch (e) {
                  onError(new Error(`Failed to parse event: ${e}`));
                }
              }
            }
          }
          // A clean end is an invitation to resume, not a failure, so it
          // is not surfaced as an error.
          attempt = -1;
        } catch (err) {
          if (aborted) return;
          // A genuine transport failure is reported once and then retried
          // with a bounded backoff, so a blip does not strand the replay.
          onError(err instanceof Error ? err : new Error(String(err)));
          await new Promise((r) => setTimeout(r, Math.min(1_000 * 2 ** attempt, 8_000)));
        }
      }
    })();

    return () => {
      aborted = true;
    };
  }

  async start(sessionId: string, intervalMs = 900): Promise<void> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/start`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interval_ms: intervalMs }),
      }
    );
    if (!res.ok) throw new Error(`Failed to start: ${res.status}`);
  }

  async pause(sessionId: string): Promise<void> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/pause`,
      { method: "POST" }
    );
    if (!res.ok) throw new Error(`Failed to pause: ${res.status}`);
  }

  async advance(sessionId: string): Promise<AdvanceResult> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/advance`,
      { method: "POST" }
    );

    if (res.ok) {
      // The committed frame, verbatim. A non-numeric sequence is not a
      // canonical commit and is reported as no movement.
      const frame = (await res.json().catch(() => ({}))) as { sequence?: number | string };
      const seq = Number(frame?.sequence);
      return Number.isFinite(seq) ? { ok: true, sequence: seq } : { ok: true };
    }

    if (res.status === 409) {
      const body = await res.json();
      return {
        ok: false,
        status: 409,
        message: body.reason || "Human approval required",
      };
    }

    throw new Error(`Advance failed: ${res.status}`);
  }

  /**
   * Submit the runtime's own `approval_payload_template` verbatim, with
   * only the client-generated idempotency key added. The frontend never
   * re-derives the plan diff hash or re-shapes an action: altering any
   * bound value invalidates the approval and commits zero mutations.
   */
  async approve(
    sessionId: string,
    binding: Record<string, unknown>
  ): Promise<{ receipt?: { receipt_id?: string }; duplicate?: boolean }> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/approve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(binding),
      }
    );
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(`Approval failed: ${res.status} ${detail.detail ?? ""}`.trim());
    }
    return await res.json();
  }

  /**
   * Enter an isolated proof branch. Refused with
   * `409 PROOF_BRANCH_NOT_AVAILABLE_YET` before event 22.
   */
  async enterBranch(
    sessionId: string,
    proofType: "vague" | "complete"
  ): Promise<BranchResult> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/branch`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proof: proofType }),
      }
    );
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail ?? `Failed to enter branch: ${res.status}`);
    }
    return await res.json();
  }

  /** Return to canonical. The runtime restores byte-identical state. */
  async exitBranch(sessionId: string): Promise<void> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/branch`,
      { method: "DELETE" }
    );
    if (!res.ok) throw new Error(`Failed to exit branch: ${res.status}`);
  }

  async reset(sessionId: string): Promise<SessionSnapshot> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/reset`,
      { method: "POST" }
    );
    if (!res.ok) throw new Error(`Failed to reset: ${res.status}`);
    return await res.json();
  }
}
