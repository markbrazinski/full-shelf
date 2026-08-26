// =====================================================================
// Session Bridge: adapts session lifecycle to beat-based interface
// =====================================================================
// Minimal adapter: holds a session, maps beat routing to cursor
// advancement, bridges approval calls. Keeps the old App.tsx
// interface intact while driving a real session backend.
// P1: replace this with direct session-driven App after cutover.

import type { FullShelfDataSource } from "./FullShelfDataSource";
import type { FullShelfProjection, BeatId } from "../types/fullShelf";
import { GoldenRuntimeDataSource } from "./GoldenRuntimeDataSource";

// P1: use cursor-to-beat mapping for debug controls
// const BEAT_TO_CURSOR: Record<string, number> = {
//   healthy: 5,
//   truckFailure: 6,
//   revisionReview: 8,
//   dispatchSchematic: 10,
//   rev08Active: 10,
//   recallProcessing: 11,
//   custodyEstablished: 18,
//   governedRecovery: 20,
//   governanceRefusal: 21,
//   partnerEvidenceVague: 23,
//   partnerEvidenceComplete: 23,
//   history: 25,
//   tomorrowsDraft: 24,
// };

export class SessionBridgeDataSource implements FullShelfDataSource {
  private backend: GoldenRuntimeDataSource;
  private sessionId: string = "";
  private unsubscribe: (() => void) | null = null;
  private projection: FullShelfProjection | null = null;
  private subscribers: Array<{
    onUpdate: () => void;
    onError: (err: Error) => void;
  }> = [];

  constructor() {
    this.backend = new GoldenRuntimeDataSource();
  }

  async init(): Promise<void> {
    const snap = await this.backend.createSession();
    this.sessionId = snap.session_id;
    this.projection = await this.backend.getProjection(snap.session_id);

    // Start autoplay
    await this.backend.start(snap.session_id, 900);

    // Subscribe to SSE
    if (this.unsubscribe) this.unsubscribe();
    this.unsubscribe = this.backend.subscribe(
      snap.session_id,
      "",
      () => {
        // Re-fetch on every event
        this.backend
          .getProjection(snap.session_id)
          .then((proj) => {
            this.projection = proj;
            this.subscribers.forEach((sub) => sub.onUpdate());
          })
          .catch((e) => {
            this.subscribers.forEach((sub) => sub.onError(e));
          });
      },
      (err) => {
        this.subscribers.forEach((sub) => sub.onError(err));
      }
    );
  }

  async getProjection(_beatId: BeatId): Promise<FullShelfProjection> {
    if (!this.projection) throw new Error("Not initialized");
    return this.projection;
  }

  subscribeToProjectionUpdates(
    onUpdate: () => void,
    onError: (err: Error) => void
  ): () => void {
    const sub = { onUpdate, onError };
    this.subscribers.push(sub);
    return () => {
      this.subscribers = this.subscribers.filter((s) => s !== sub);
    };
  }

  async approveRepair(binding: {
    proposalId?: string;
    tenantId: string;
    operatingDay: string;
    incidentId?: string;
    planId?: string;
    sourceRevision?: string;
    proposedRevision?: string;
    planDiff?: {
      rerouteOrderId: string;
      rerouteCases: number;
      rerouteTargetVehicle: string;
      pickupOrderId: string;
      pickupCases: number;
    };
  }): Promise<void> {
    if (!this.sessionId) throw new Error("Not initialized");

    const approval = {
      plan_id: binding.planId ?? null,
      incident_id: binding.incidentId ?? null,
      expected_revision: binding.sourceRevision ?? null,
      target_revision: binding.proposedRevision ?? null,
      actions: ["REROUTE", "PICKUP"],
      plan_diff_hash: null,
      idempotency_key: crypto.randomUUID(),
    };

    await this.backend.approve(this.sessionId, approval);
  }

  async cleanup(): Promise<void> {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
  }
}
