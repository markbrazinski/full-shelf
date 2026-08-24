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

export interface FullShelfDataSource {
  getProjection(beatId: BeatId): Promise<FullShelfProjection>;
}
