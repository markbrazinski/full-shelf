// =====================================================================
// Minimal session-focused normalizer
// =====================================================================
// P1 DEFERRED: This is a quick bridge that reuses the old normalize()
// where possible and adds minimal new mappings for recovery_proposal,
// reference_locations, and branch state. Full normalize.ts rewrite is
// deferred — this variant is good enough for the golden-path journey.

import type { RawProjection } from "./contract/transport";
import { normalize as normalizeOld } from "./contract/normalize";
import type { FullShelfProjection, MapLocation, RecoveryProposalView } from "../types/fullShelf";

export function normalize(raw: RawProjection): FullShelfProjection {
  // Map cursor to a beat ID for the old normalizer
  const beatId: "healthy" = "healthy"; // P1: derive from cursor
  const old = normalizeOld(raw, beatId);

  // Add recovery proposal mapping if present (advisory, cursor 19)
  let recoveryProposal: RecoveryProposalView | undefined;
  const rp = raw.current_day?.recovery_proposal;
  if (rp) {
    const exp = rp.explanation;
    recoveryProposal = {
      question: "Can we recover safely?",
      headline: exp
        ? `${exp.cases_allocated} safe replacements for ${exp.agencies_allocated} agencies`
        : "Recovery proposed",
      items: [], // P1: map from allocations
      safeReplacements: {
        total: exp?.cases_allocated ?? 0,
        breakdown: exp?.statement ?? "",
      },
      shortfall: {
        value: exp?.cases_short ?? 0,
        agency: rp.shortfalls?.[0]?.agency_id ?? "unknown",
        note: "Unmet demand",
      },
    };
  }

  // Add reference locations mapping (all cursors from 5+)
  let referenceLocations: MapLocation[] | undefined;
  if (raw.reference_locations?.locations) {
    referenceLocations = raw.reference_locations.locations.map((loc) => ({
      id: loc.location_id,
      name: loc.name,
      lat: loc.latitude,
      lon: loc.longitude,
      role: loc.role,
      agencyId: loc.agency_id,
    }));
  }

  // Add branch state mapping (only when in a branch)
  let branchState: { authority: "ISOLATED"; proofLabel: string } | undefined;
  if (raw.authority_scope === "ISOLATED") {
    branchState = {
      authority: "ISOLATED",
      proofLabel: "ISOLATED SELECTED PROOF",
    };
  }

  // Add cursor from projection_boundary.as_of if parseable
  let cursor: number | undefined;
  // P1: parse cursor from the projection or SSE event sequence

  return {
    ...old,
    recoveryProposal,
    referenceLocations,
    branchState,
    cursor,
  };
}
