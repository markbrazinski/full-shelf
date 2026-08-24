// =====================================================================
// Full Shelf — beat ↔ as_of boundary map
// ---------------------------------------------------------------------
// Mirrors tools/replay/fixtures/index.json at contract tag v2. Each of
// the 12 operational beats is a fixed as_of instant; History is the 13th
// view and is a read-only lens over the last boundary, not its own beat.
//
// as_of is always sent explicitly so a refresh returns byte-identical
// truth rather than "latest".
// =====================================================================

import type { BeatId, BeatMeta } from "../../types/fullShelf";

export interface BeatBoundary {
  id: BeatId;
  asOf: string;
  /** Tomorrow's draft is only ever requested explicitly. */
  includeNextDayDraft: boolean;
  time: string;
  label: string;
}

export const BEAT_BOUNDARIES: BeatBoundary[] = [
  { id: "healthy",            asOf: "2026-08-14T08:05:00+00:00", includeNextDayDraft: false, time: "08:05", label: "Healthy" },
  { id: "truckFailure",       asOf: "2026-08-14T08:20:00+00:00", includeNextDayDraft: false, time: "08:20", label: "Truck failure" },
  { id: "revisionReview",     asOf: "2026-08-14T08:21:00+00:00", includeNextDayDraft: false, time: "08:21", label: "Revision review" },
  { id: "dispatchSchematic",  asOf: "2026-08-14T08:22:00+00:00", includeNextDayDraft: false, time: "08:22", label: "Planned dispatch" },
  { id: "rev08Active",        asOf: "2026-08-14T08:24:00+00:00", includeNextDayDraft: false, time: "08:24", label: "rev08 active" },
  { id: "recallReceived",     asOf: "2026-08-14T09:36:00+00:00", includeNextDayDraft: false, time: "09:36", label: "Recall received" },
  { id: "recallProcessing",   asOf: "2026-08-14T10:04:00+00:00", includeNextDayDraft: false, time: "10:04", label: "Recall processing" },
  { id: "custodyEstablished", asOf: "2026-08-14T10:05:00+00:00", includeNextDayDraft: false, time: "10:05", label: "Custody established" },
  { id: "governedRecovery",   asOf: "2026-08-14T10:10:00+00:00", includeNextDayDraft: false, time: "10:10", label: "Governed recovery" },
  { id: "governanceRefusal",  asOf: "2026-08-14T10:13:00+00:00", includeNextDayDraft: false, time: "10:13", label: "Governance refusal" },
  { id: "todaysOutcome",      asOf: "2026-08-14T16:30:00+00:00", includeNextDayDraft: false, time: "16:30", label: "Today's Outcome" },
  { id: "tomorrowsDraft",     asOf: "2026-08-14T17:00:00+00:00", includeNextDayDraft: true,  time: "17:00", label: "Tomorrow" },
  // History reads the terminal boundary; it never advances the day.
  { id: "history",            asOf: "2026-08-14T17:00:00+00:00", includeNextDayDraft: false, time: "17:00", label: "History" },
];

const BY_ID = new Map(BEAT_BOUNDARIES.map((b) => [b.id, b]));

export function boundaryFor(beatId: BeatId): BeatBoundary {
  const b = BY_ID.get(beatId);
  if (!b) throw new Error(`Unknown beat \`${beatId}\``);
  return b;
}

/** Navigator metadata; History is presented separately in the shell. */
export const BEATS: BeatMeta[] = BEAT_BOUNDARIES
  .filter((b) => b.id !== "history")
  .map(({ id, time, label }) => ({ id, time, label }));
