// =====================================================================
// Full Shelf — data-source seam
// ---------------------------------------------------------------------
// This interface is the contract every data source implements. The
// bundled implementation is FixtureDataSource (deterministic synthetic).
// Claude Code adds a RecordedReplayDataSource and a LiveHttpDataSource
// implementing THIS SAME interface — no component changes required.
// See INTEGRATION_HANDOFF.md for exactly where to add them.
// =====================================================================

import type { BeatId, FullShelfProjection } from "../types/fullShelf";

export interface FullShelfDataSource {
  getProjection(beatId: BeatId): Promise<FullShelfProjection>;
}
