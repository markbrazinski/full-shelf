// =====================================================================
// Golden Runtime session normalizer
// ---------------------------------------------------------------------
// Wraps the contract-v2 normalizer and adds the session-only facts the
// Golden Runtime Controller carries that contract v2 does not:
//
//   * cursor           — derived from projection_boundary.as_of
//   * repair_proposal  — runtime emits `actions`, contract v2 `plan_diff`
//   * recovery_proposal — event 19 ADVISORY, distinct from event 20 COMMITTED
//   * reference_locations — the six configured East Bay coordinates
//   * branch state     — `authority: ISOLATED` + `proof_label`
//
// Every value below is read from the wire. Nothing is invented, and no
// field belonging to a later event is synthesized early.
// =====================================================================

import type { RawProjection, RawRepairProposal } from "./contract/transport";
import { normalize as normalizeContract } from "./contract/normalize";
import type {
  FleetVehicleView,
  FullShelfProjection,
  MapLocation,
  RecoveryProposalView,
  RepairProposalView,
} from "../types/fullShelf";


/**
 * The runtime's repair_proposal carries `actions[]`; contract v2 declares
 * `plan_diff`. Same two facts, two spellings. Read the runtime shape.
 */
interface RuntimeRepairProposal extends RawRepairProposal {
  incident_id?: string | null;
  expected_revision?: string | null;
  target_revision?: string | null;
  status?: string | null;
  actions?: {
    order_id: string;
    agency: string | null;
    cases: number;
    lot_id: string | null;
    from_vehicle: string | null;
    to_vehicle: string | null;
    disposition: string;
  }[];
  capacity_arithmetic?: {
    vehicle_id: string;
    existing_cases: number;
    added_cases: number;
    resulting_cases: number;
    capacity_cases: number;
    statement: string;
    both_orders_would_not_fit: string;
  };
  approval_payload_template?: Record<string, unknown>;
  approval_receipt_id?: string | null;
}

interface RuntimeRecoveryProposal {
  proposal_id?: string;
  incident_id?: string | null;
  status?: string;
  safe_lot_id?: string | null;
  allocations?: { agency_id: string | null; cases: number; status: string }[];
  total_proposed_cases?: number;
  shortfalls?: { agency_id: string | null; shortfall_id: string; cases: number; status: string }[];
  mutation_applied?: boolean;
  commits_at_event?: number | null;
}

interface RuntimeReferenceLocation {
  location_id: string;
  display_name?: string;
  name?: string;
  street_address?: string;
  latitude: number;
  longitude: number;
  role: string;
  custody_node_id?: string | null;
  agency_id?: string | null;
  order_ids?: string[];
  match_quality?: string;
}

/**
 * The runtime projection carries session facts on top of contract v2.
 * Declared here so nothing has to be read through `any`.
 */
type RuntimeProjection = RawProjection & {
  authority?: string;
  proof_label?: string;
  reference_locations?: {
    disclosure: string;
    live_gps?: boolean;
    location_mode?: string;
    geocode_source?: string;
    geocode_license?: string;
    locations: RuntimeReferenceLocation[];
  };
  current_day: RawProjection["current_day"] & {
    recovery_proposal?: RuntimeRecoveryProposal;
  };
};

/**
 * Scenario wall-clock → canonical cursor. `effective_at` is the only
 * ordering fact the projection carries, and several events share a
 * timestamp, so this resolves to the FIRST event at that time and the
 * caller refines it with the SSE sequence it actually observed.
 */
const CURSOR_BY_CLOCK: [string, number][] = [
  ["08:05", 5], ["08:20", 6], ["08:21", 8], ["08:24", 9],
  ["09:36", 11], ["10:04", 13], ["10:05", 15], ["10:06", 16],
  ["10:07", 17], ["10:10", 18], ["10:12", 21], ["10:13", 22],
  ["16:30", 23], ["17:00", 24],
];

function cursorFromBoundary(asOf: string): number | undefined {
  const hhmm = /T(\d{2}:\d{2})/.exec(asOf)?.[1];
  if (!hhmm) return undefined;
  return CURSOR_BY_CLOCK.find(([t]) => t === hhmm)?.[1];
}

export function normalize(raw: RawProjection, observedCursor?: number): FullShelfProjection {
  const rt = raw as RuntimeProjection;

  // The contract normalizer is beat-parameterized only for `outcome` and
  // `history`; every other surface self-gates on projected presence.
  const base = normalizeContract(raw, "healthy");

  const boundaryCursor = cursorFromBoundary(raw.projection_boundary.as_of);
  const cursor = observedCursor ?? boundaryCursor;

  // ---- repair proposal (event 8; APPROVED at 9) ----------------------
  const repairProposal = mapRepairProposal(rt.current_day.repair_proposal as RuntimeRepairProposal | null);

  // ---- advisory recovery proposal (event 19 ONLY) --------------------
  // Distinct from `current_day.recovery`, which is the COMMITTED
  // allocation and does not exist until event 20.
  const recoveryProposal = mapRecoveryProposal(rt.current_day.recovery_proposal);

  // ---- the six configured reference locations -----------------------
  const referenceLocations: MapLocation[] | undefined = rt.reference_locations?.locations?.map((loc) => ({
    id: loc.location_id,
    // The runtime spells this `display_name`.
    name: loc.display_name ?? loc.name ?? loc.location_id,
    lat: loc.latitude,
    lon: loc.longitude,
    role: loc.role,
    agencyId: loc.agency_id ?? null,
    address: loc.street_address ?? null,
    custodyNodeId: loc.custody_node_id ?? null,
    orderIds: loc.order_ids ?? [],
  }));

  const locationDisclosure = rt.reference_locations?.disclosure;

  // ---- fleet (event 5 onward; Truck 1 alarms at event 6) -------------
  const fleet: FleetVehicleView[] | undefined = rt.current_day.vehicles?.map((v) => ({
    vehicleId: v.vehicle_id,
    displayName: v.display_name ?? v.name ?? v.vehicle_id,
    status: v.status ?? "UNKNOWN",
    isOperational: v.is_operational !== false,
    refrigerationCapable: v.refrigeration_capable === true,
    refrigerationOperational: v.refrigeration_operational === true,
    capacityCases: v.capacity_cases ?? null,
    manifestCases: v.manifest_cases ?? v.assigned_cases ?? null,
    remainingCases: v.remaining_cases ?? null,
    assignedOrders: v.assigned_orders ?? [],
    revision: v.revision ?? null,
    alarm: {
      active: v.alarm?.active === true,
      kind: v.alarm?.kind ?? null,
      incidentId: v.alarm?.incident_id ?? null,
      raisedAtEvent: v.alarm?.raised_at_event ?? null,
    },
    telemetry: v.telemetry
      ? {
          liveGps: v.telemetry.live_gps,
          positionAvailable: v.telemetry.position_available,
          basis: v.telemetry.basis,
          disclosure: v.telemetry.disclosure,
        }
      : null,
  }));

  // ---- isolated proof branch ----------------------------------------
  // `authority` (not `authority_scope`, which is the tenant/day scope on
  // every projection) is what flips to ISOLATED inside a branch.
  const branchState =
    rt.authority === "ISOLATED"
      ? { authority: "ISOLATED" as const, proofLabel: rt.proof_label ?? "ISOLATED SELECTED PROOF" }
      : undefined;

  return {
    ...base,
    cursor,
    repairProposal: repairProposal ?? base.repairProposal,
    recoveryProposal,
    referenceLocations,
    locationDisclosure,
    fleet,
    branchState,
  };
}

function mapRepairProposal(rp: RuntimeRepairProposal | null | undefined): RepairProposalView | undefined {
  if (!rp?.proposal_id) return undefined;

  // Prefer the runtime's `actions`; fall back to contract v2's plan_diff.
  const reroute = rp.actions?.find((a) => a.disposition === "TRUCK_2");
  const pickup = rp.actions?.find((a) => a.disposition === "PARTNER_PICKUP");
  const diff = rp.plan_diff;

  const rerouteOrderId = reroute?.order_id ?? diff?.reroute_order_id;
  const pickupOrderId = pickup?.order_id ?? diff?.pickup_order_id;
  if (!rerouteOrderId || !pickupOrderId) return undefined;

  const cap = rp.capacity_arithmetic;

  return {
    proposalId: rp.proposal_id,
    sourceEventId: rp.source_event_id ?? null,
    planId: rp.plan_id ?? null,
    sourceRevision: rp.expected_revision ?? rp.source_revision ?? null,
    proposedRevision: rp.target_revision ?? rp.proposed_revision ?? null,
    failedVehicleId: rp.failed_vehicle_id ?? reroute?.from_vehicle ?? null,
    rerouteOrderId,
    rerouteCases: reroute?.cases ?? diff?.reroute_cases ?? 0,
    rerouteTargetVehicle: reroute?.to_vehicle ?? diff?.reroute_target_vehicle ?? "—",
    pickupOrderId,
    pickupCases: pickup?.cases ?? diff?.pickup_cases ?? 0,
    planDiffHash: rp.plan_diff_hash ?? null,
    absorbing: {
      vehicleId: cap?.vehicle_id ?? rp.absorbing_vehicle?.vehicle_id ?? null,
      capacityCases: cap?.capacity_cases ?? rp.absorbing_vehicle?.capacity_cases ?? null,
      committedCases: cap?.existing_cases ?? rp.absorbing_vehicle?.committed_cases ?? null,
      projectedCases: cap?.resulting_cases ?? rp.absorbing_vehicle?.projected_cases ?? null,
    },
    // Both orders cannot fit — the arithmetic the runtime actually states.
    infeasibilityStatement: cap?.both_orders_would_not_fit ?? null,
    capacityStatement: cap?.statement ?? null,
    // The runtime supplies a submit-ready binding; only the idempotency
    // key is ours. Never re-derive a hash or re-shape an action here.
    approvalPayloadTemplate: rp.approval_payload_template ?? null,
    // PROPOSED at event 8, APPROVED with a receipt at event 9.
    status: rp.status ?? "PROPOSED",
    approvalReceiptId: rp.approval_receipt_id ?? null,
    authority: rp.authority ?? "AGENT_PROPOSAL",
    approvalRequired: rp.approval_required !== false,
    activationSupported: rp.activation_supported === true,
  };
}

function mapRecoveryProposal(rp: RuntimeRecoveryProposal | undefined): RecoveryProposalView | undefined {
  if (!rp) return undefined;

  const allocations = (rp.allocations ?? []).filter((a) => a.agency_id);
  const shortfall = rp.shortfalls?.[0];
  const total = rp.total_proposed_cases ?? allocations.reduce((n, a) => n + a.cases, 0);

  return {
    question: "What can be replaced from safe stock?",
    headline: `${total} safe replacements proposed for ${allocations.length} agencies`,
    // Advisory until the runtime commits it at event 20.
    status: rp.status ?? "PROPOSED",
    mutationApplied: rp.mutation_applied === true,
    commitsAtEvent: rp.commits_at_event ?? null,
    safeLotId: rp.safe_lot_id ?? null,
    allocations: allocations.map((a) => ({
      agencyId: a.agency_id as string,
      cases: a.cases,
      status: a.status,
    })),
    items: allocations.map((a) => ({
      text: `${a.agency_id} · ${a.cases} cases from safe stock`,
      tone: "info" as const,
      authorityClass: "AGENT_PROPOSAL" as const,
    })),
    safeReplacements: {
      total,
      breakdown: allocations.map((a) => `${a.agency_id}: ${a.cases}`).join(" · "),
    },
    shortfall: {
      value: shortfall?.cases ?? 0,
      agency: shortfall?.agency_id ?? "—",
      note: shortfall ? `${shortfall.shortfall_id} remains open.` : "No shortfall reported.",
    },
  };
}
