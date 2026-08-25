// =====================================================================
// Full Shelf — data-source seam
// ---------------------------------------------------------------------
// This interface is the contract every data source implements. The
// runtime implementations are ReplayHttpDataSource and
// LiveOrchestratorDataSource (data/ProjectionHttpDataSource.ts), chosen
// by VITE_DATA_SOURCE in env.ts. Both share one validator and one
// normalizer, so replay cannot drift from live.
// =====================================================================

import type { BeatId, FullShelfProjection } from "../types/fullShelf";

/** The exact change a human is approving. Bound to the proposal's diff. */
export interface RepairApprovalRequest {
  proposalId: string;
  tenantId: string;
  operatingDay: string;
  incidentId: string;
  planId: string;
  sourceRevision: string;
  proposedRevision: string;
  /** The exact diff the proposal bound. Never composed in the browser. */
  planDiff: {
    rerouteOrderId: string;
    rerouteCases: number;
    rerouteTargetVehicle: string;
    pickupOrderId: string;
    pickupCases: number;
  };
}

export interface FullShelfDataSource {
  getProjection(beatId: BeatId): Promise<FullShelfProjection>;

  /** Subscribe to cursor-only committed receipt notifications. */
  subscribeToProjectionUpdates?(
    onUpdate: () => void,
    onError: (error: unknown) => void,
  ): () => void;

  /**
   * Approve a pending repair proposal.
   *
   * Runs the real verified-human -> KMS -> ledger path. The browser never
   * talks to the ledger directly; this posts to the orchestrator, which
   * holds the operator token for independent verification.
   *
   * Rejects when the approval was not committed. Callers must treat a
   * rejection as "authoritative state did not change".
   */
  approveRepair(request: RepairApprovalRequest): Promise<void>;
}
