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
  sequence: number;
  effective_at: string;
  event_type: string;
  action_required: boolean;
  severity: string;
  activity_entry: {
    headline: string;
  };
}

export interface AdvanceResult {
  ok: boolean;
  status?: number;
  message?: string; // "HUMAN_APPROVAL_REQUIRED", "REPLAY_COMPLETE", "CANONICAL_ADVANCE_BLOCKED_IN_BRANCH"
}

interface GoldenRuntimeConfig {
  baseUrl: string;
}

export class GoldenRuntimeDataSource {
  private config: GoldenRuntimeConfig;

  constructor(baseUrl = "http://127.0.0.1:8788") {
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

  async getProjection(sessionId: string): Promise<FullShelfProjection> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/projection`
    );
    if (!res.ok) throw new Error(`Failed to get projection: ${res.status}`);
    const raw = await res.json();
    const normalized = normalize(raw);
    return normalized;
  }

  subscribe(
    sessionId: string,
    lastEventId: string | undefined,
    onEvent: (envelope: EventEnvelope) => void,
    onError: (err: Error) => void
  ): () => void {
    let aborted = false;

    (async () => {
      try {
        const headers: Record<string, string> = {
          Accept: "text/event-stream",
        };
        if (lastEventId) {
          headers["Last-Event-ID"] = lastEventId;
        }

        const res = await fetch(
          `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/stream`,
          { headers }
        );
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
                onEvent(envelope);
              } catch (e) {
                onError(new Error(`Failed to parse event: ${e}`));
              }
            }
          }
        }
      } catch (err) {
        if (!aborted) {
          onError(err instanceof Error ? err : new Error(String(err)));
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
      return { ok: true };
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

  async approve(
    sessionId: string,
    binding: {
      plan_id: string | null;
      incident_id: string | null;
      expected_revision: string | null;
      target_revision: string | null;
      actions: string[];
      plan_diff_hash: string | null;
      idempotency_key: string;
    }
  ): Promise<void> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/approve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(binding),
      }
    );
    if (!res.ok) throw new Error(`Approval failed: ${res.status}`);
  }

  async enterBranch(
    sessionId: string,
    proofType: "vague" | "complete"
  ): Promise<void> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/branch`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proof: proofType }),
      }
    );
    if (!res.ok) throw new Error(`Failed to enter branch: ${res.status}`);
  }

  async exitBranch(
    sessionId: string
  ): Promise<{ projection: FullShelfProjection }> {
    const res = await fetch(
      `${this.config.baseUrl}/api/v1/replay/sessions/${sessionId}/branch`,
      { method: "DELETE" }
    );
    if (!res.ok) throw new Error(`Failed to exit branch: ${res.status}`);
    const body = await res.json();
    const normalized = normalize(body.projection);
    return { projection: normalized };
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
