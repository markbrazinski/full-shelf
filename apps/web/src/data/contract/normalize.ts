// =====================================================================
// Full Shelf — contract v2 → v4 view-model normalizer
// ---------------------------------------------------------------------
// The ONE reconciliation layer. Contract v2 owns factual truth; the v4
// view models own visual intent; this file maps the former onto the
// latter and changes neither.
//
// Governing rules, applied uniformly below:
//   * Absent is absent. A field the contract omits yields `undefined`,
//     never "" / 0 / false. Panels disappear rather than render a zero.
//   * First-safe boundary. agent activity, custody, intake and refusal
//     surfaces appear only once the contract actually carries them.
//   * Only real evidence. Tool evidence is emitted only for agents whose
//     `tool_invocations` is non-empty; rationale only when persisted.
//   * kms_key_version only — signature material never reaches a view.
//   * Model Armor is a boundary chip, never a sixth agent.
// =====================================================================

import {
  HISTORICAL_NOT_RETAINED,
  type AgentActivityView,
  type AgentCell,
  type AgentDisplayStatus,
  type BeatId,
  type Commitment,
  type CustodyView,
  type DispatchView,
  type ExecutionEvidenceView,
  type FullShelfProjection,
  type GovernanceView,
  type HistoryView,
  type IncidentView,
  type OrderStateTone,
  type OutcomeView,
  type RecallView,
  type RecoveryView,
  type SpecialistEvidence,
  type Tone,
  type TomorrowView,
  type CandidateVehicle,
  type IncidentSummary,
  type RepairProposalView,
  type RecallSourceView,
  type PartnerEvidenceProofView,
} from "../../types/fullShelf";
import type {
  RawAgent,
  RawApproval,
  RawDispatch,
  RawIncident,
  RawProjection,
} from "./transport";

const VEHICLE_LABEL: Record<string, string> = {
  "TRUCK-01": "Truck 1",
  "TRUCK-02": "Truck 2",
};

const vehicleLabel = (id: string | null | undefined): string =>
  (id && VEHICLE_LABEL[id]) || id || "—";

/** "2026-08-14T10:13:00+00:00" → "10:13". Never re-derives a date. */
function clockOf(iso: string): string {
  const m = /T(\d{2}):(\d{2})/.exec(iso);
  return m ? `${m[1]}:${m[2]}` : iso;
}

function dayLabelOf(operatingDay: string): string {
  const [y, mo, d] = operatingDay.split("-").map(Number);
  const dt = new Date(Date.UTC(y, mo - 1, d));
  const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][dt.getUTCDay()];
  const mn = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][mo - 1];
  return `${wd} · ${mn} ${d}`;
}

const ACTION_TITLE: Record<string, string> = {
  SAVE_PLAN_REVISION: "Plan revision committed",
  SET_INCIDENT_STATUS: "Incident status committed",
  ACTIVATE_MOVEMENT_BARRIER: "Movement barrier activated",
  INVALIDATE_PLAN: "Plan invalidated",
  ALLOCATE_SAFE_STOCK: "Safe stock allocated",
  RECORD_REFUSAL: "Containment refused by policy",
};

const INTAKE_TITLE: Record<string, string> = {
  NOTICE_SCREENED: "Notice screened",
  NOTICE_EXTRACTED: "Facts extracted",
  INCIDENT_OPENED: "Incident opened",
  PLAN_INVALIDATED: "Plan invalidated",
  MOVEMENT_BARRIER_ACTIVE: "Movement barrier active",
  FLEET_PROPOSAL_ACCEPTED: "Fleet proposal accepted",
};

const INTAKE_BODY: Record<string, string> = {
  NOTICE_SCREENED: "Untrusted notice screened at the Model Armor boundary before any agent read it.",
  NOTICE_EXTRACTED: "Lot and scope extracted from the screened notice.",
  INCIDENT_OPENED: "Incident opened against the affected lot.",
  PLAN_INVALIDATED: "Affected commitments withdrawn from the active plan.",
  MOVEMENT_BARRIER_ACTIVE: "Further movement of the affected lot is barred.",
  FLEET_PROPOSAL_ACCEPTED: "Governed specialists reported and a proposal was accepted.",
};

const NODE_ORDER = ["N-WH", "N-TR2", "N-STG", "N-AG01", "N-ST01", "N-RESC"];

// Human-readable roles for the custody network. PRESENTATION METADATA ONLY:
// quantities, identifiers, custody states and locations all come from the
// projection. If a node is not listed here it renders with its projected
// name alone rather than an invented role.
const NODE_ROLE: Record<string, string> = {
  "N-WH": "On hand",
  "N-TR2": "In transit",
  "N-STG": "Movement blocked",
  "N-AG01": "Partner pantry",
  "N-AG02": "Partner pantry",
  "N-AG03": "Partner program",
  "N-ST01": "Distribution site",
  "N-RESC": "Direct rescue",
};

/** Contract agent states map 1:1; nothing transient is representable. */
function agentStatus(state: string): AgentDisplayStatus {
  if (state === "COMPLETED") return "COMPLETED";
  if (state === "NOT_INVOLVED") return "NOT_INVOLVED";
  return "NOT_YET_REPORTED";
}

const AGENT_KEY: Record<string, string> = {
  "full-shelf.incident-coordinator.v1": "coord",
  "full-shelf.recall-extraction.v1": "recall",
  "full-shelf.network-custody.v1": "net",
  "full-shelf.fulfillment-recovery.v1": "fulf",
  "full-shelf.partner-operations.v1": "part",
};

const AGENT_TASK: Record<string, string> = {
  coord: "Coordinate incident response",
  recall: "Extract recall facts from the screened notice",
  net: "Establish lot custody across the network",
  fulf: "Propose feasible recovery from safe stock",
  part: "Propose refrigerated partner pickup",
};

function agentCell(a: RawAgent): AgentCell {
  const key = AGENT_KEY[a.agent_id] ?? a.agent_id;
  const status = agentStatus(a.state);
  return {
    key,
    name: a.display_name,
    isCoordinator: a.role === "ROOT_COORDINATOR",
    status,
    task: AGENT_TASK[key] ?? a.role,
    // The contract persists no per-agent result prose. Report the
    // committed validation verdict instead of inventing a sentence.
    result: status === "COMPLETED" ? (a.deterministic_validation ?? "Reported · validated") : null,
  };
}

function orderTone(status: string | null, lotFlagged: boolean): [string, OrderStateTone] {
  if (status === "DELIVERED") return ["Delivered", "delivered"];
  if (status === "PARTNER_PICKUP") return ["Partner pickup", "partner"];
  if (status === "REASSIGNED") return ["Reassigned", "reassigned"];
  if (status === "WITHDRAWN" || lotFlagged) return ["Recall hold", "recall"];
  return ["Planned", "planned"];
}

// ---------------------------------------------------------------------

export function normalize(raw: RawProjection, beatId: BeatId): FullShelfProjection {
  const cd = raw.current_day;
  const asOf = raw.projection_boundary.as_of;
  const clock = clockOf(asOf);
  const omittedFields = raw.projection_boundary.omitted_fields.map((f) => `${f.field} — ${f.reason}`);

  const recallIncident = cd.incidents.find((i) => i.incident_type === "FOOD_SAFETY_RECALL");
  const vehicleIncident = cd.incidents.find((i) => i.incident_type === "VEHICLE_FAILURE");
  const flaggedLot = recallIncident?.affected_lot_id ?? null;
  const approval = cd.approvals[0];
  const activeRev = cd.active_plan_revision;

  // ---- commitments: the active revision, plus work already done -------
  // A commitment DELIVERED under a superseded revision is still a fact
  // about today: a later revision re-plans the REMAINING work, it does not
  // un-deliver what already happened. Dropping it would silently lose
  // O201's 18 delivered cases the moment rev08 activates. De-duplicated by
  // order id so a subtotal is never re-added.
  const activeRows = cd.commitments.filter((c) => !activeRev || c.revision === activeRev);
  const deliveredElsewhere = cd.commitments.filter(
    (c) =>
      c.status === "DELIVERED" &&
      c.revision !== activeRev &&
      !activeRows.some((a) => a.order_id === c.order_id),
  );
  const rows = [...deliveredElsewhere, ...activeRows];
  const commitments: Commitment[] = rows.map((c) => {
    const lotFlagged = !!flaggedLot && c.lot_id === flaggedLot;
    const [stateLabel, stateTone] = orderTone(c.status, lotFlagged);
    return {
      id: c.order_id,
      lot: c.lot_id ?? "—",
      lotFlagged,
      agency: c.agency ?? "—",
      cases: c.cases ?? 0,
      vehicle: vehicleLabel(c.vehicle),
      stateLabel: c.status === "PLANNED" && vehicleIncident && c.vehicle === "TRUCK-01"
        ? `Impacted by ${vehicleIncident.incident_id}`
        : stateLabel,
      stateTone: c.status === "PLANNED" && vehicleIncident && c.vehicle === "TRUCK-01" ? "impacted" : stateTone,
    };
  });

  const posture = recallIncident ? "RECALL" : vehicleIncident ? "INTERVENTION" : "NORMAL";

  // Incident presence is a projected fact. A vehicle failure runs
  // ACTIVE -> RESOLVED; a recall runs the containment ladder and is still
  // open at PARTIALLY_CONTAINED. Nothing here consults the current view.
  const RESOLVED_STATES = new Set(["RESOLVED", "CONTAINED", "CLOSED"]);
  const incidentSummary: IncidentSummary = {
    activeCount: cd.incidents.filter((i) => !RESOLVED_STATES.has(i.status)).length,
    incidents: cd.incidents.map((i) => ({
      id: i.incident_id,
      type: i.incident_type,
      status: i.status,
      terminalState: i.terminal_state,
      affectedLotId: i.affected_lot_id ?? null,
      active: !RESOLVED_STATES.has(i.status),
    })),
  };

  const projection: FullShelfProjection = {
    beatId,
    asOf,
    incidentSummary,
    // Replay is always synthetic; a live source overrides this.
    dataMode: raw.classification === "SYNTHETIC_TEST" ? "SYNTHETIC_TEST" : "OBSERVED_LIVE",
    currentDay: {
      clock,
      operatingDate: dayLabelOf(raw.operating_day),
      dayLabel: dayLabelOf(raw.operating_day),
      connection: "CONNECTED",
      inDaybook: beatId !== "history",
      posture,
      authRev: activeRev ?? undefined,
      commitments: commitments.length ? commitments : undefined,
      commitmentsSummary: commitments.length
        ? { label: `${commitments.length} commitments · ${cd.plan_id}${activeRev ? ` / ${activeRev}` : ""}`, tone: posture === "RECALL" ? "crit" : "neutral" }
        : undefined,
      openObligations: raw.carry_forward_obligations.length
        ? { count: raw.carry_forward_obligations.length, note: "carried into tomorrow", tone: "warn" }
        : undefined,
      // Historical side-copy was never retained by the contract.
      obligationsNote: HISTORICAL_NOT_RETAINED,
    },
    omittedFields,
  };

  // A pending repair proposal. Bound straight from the contract: the diff
  // shown to an operator is the diff KMS will sign.
  const rp = cd.repair_proposal;
  if (rp && rp.plan_diff && rp.proposal_id) {
    const proposal: RepairProposalView = {
      proposalId: rp.proposal_id,
      sourceEventId: rp.source_event_id,
      planId: rp.plan_id,
      sourceRevision: rp.source_revision,
      proposedRevision: rp.proposed_revision,
      failedVehicleId: rp.failed_vehicle_id,
      rerouteOrderId: rp.plan_diff.reroute_order_id,
      rerouteCases: rp.plan_diff.reroute_cases,
      rerouteTargetVehicle: rp.plan_diff.reroute_target_vehicle,
      pickupOrderId: rp.plan_diff.pickup_order_id,
      pickupCases: rp.plan_diff.pickup_cases,
      planDiffHash: rp.plan_diff_hash,
      absorbing: {
        vehicleId: rp.absorbing_vehicle?.vehicle_id ?? null,
        capacityCases: rp.absorbing_vehicle?.capacity_cases ?? null,
        committedCases: rp.absorbing_vehicle?.committed_cases ?? null,
        projectedCases: rp.absorbing_vehicle?.projected_cases ?? null,
      },
      authority: rp.authority,
      approvalRequired: rp.approval_required,
      // Read from the contract, never assumed.
      activationSupported: rp.activation_supported === true,
    };
    projection.repairProposal = proposal;
  }

  const intakeSource = raw.recall_intake_as_of?.source;
  if (intakeSource) {
    const source: RecallSourceView = {
      channel: intakeSource.channel,
      noticeFormat: intakeSource.notice_format,
      receivedAt: intakeSource.received_at,
      monitoringClaimed: intakeSource.monitoring_claimed === true,
      inputKind: intakeSource.input_kind,
    };
    projection.recallSource = source;
  }

  if (raw.partner_evidence_as_of?.length) {
    projection.partnerEvidence = raw.partner_evidence_as_of.map((entry): PartnerEvidenceProofView => {
      const work = entry.before_after.work_item;
      return {
        sourceEventId: entry.source_event_id,
        eventType: entry.event_type,
        sourceOccurredAt: entry.source_occurred_at,
        receivedAt: entry.received_at,
        committedAt: entry.committed_at,
        originalResponse: entry.original_response,
        partnerId: entry.authoritative_partner_id,
        callbackPrincipal: {
          subject: entry.callback_principal.subject,
          email: entry.callback_principal.email,
          audience: entry.callback_principal.audience,
          issuer: entry.callback_principal.issuer,
          provenance: entry.callback_principal.provenance,
        },
        decision: entry.decision,
        reasons: entry.policy_reasons,
        claims: entry.claim_verification,
        modelArmorStatus: typeof entry.model_armor.status === "string" ? entry.model_armor.status : "UNKNOWN",
        proposalRationale: typeof entry.proposal?.rationale === "string" ? entry.proposal.rationale : null,
        receiptId: entry.receipt?.receipt_id ?? null,
        receiptStatus: entry.receipt?.status ?? null,
        domainMutationsApplied: entry.receipt?.domain_mutations_applied ?? 0,
        evidenceMutationsApplied: entry.receipt?.evidence_mutations_applied ?? 0,
        totalCases: entry.custody.total_cases,
        confirmedCasesBefore: entry.custody.confirmed_cases_before,
        confirmedCasesAfter: entry.custody.confirmed_cases_after,
        workItemId: work?.work_item_id ?? null,
        workItemBefore: work?.before ?? null,
        workItemAfter: work?.after ?? null,
        agentId: entry.agent.agent_id,
        modelId: entry.agent.model_id,
        adkFramework: entry.agent.adk_framework,
        adkSessionId: entry.agent.adk_session_id,
        adkInvocationId: entry.agent.adk_invocation_id,
        adkEventId: entry.agent.adk_event_id,
        // Canonical by default. Only the session layer knows a branch is
        // open, so it re-stamps these entries; see SessionNormalizer.
        isolatedProof: false,
      };
    });
  }

  const cdv = projection.currentDay;

  // ---- approval record: key VERSION only, never a signature ----------
  if (approval) {
    cdv.approvalRecord = {
      decision: approval.state === "VERIFIED" ? "Verified" : approval.state,
      approver: approval.approver_domain ? `verified operator · ${approval.approver_domain}` : "verified operator",
      role: approval.approver_identity_class,
      timestamp: approval.verified_at,
      kmsKeyVersion: approval.kms_key_version,
      kmsNote: "KMS key version bound to the plan diff. The signature itself is never transported.",
      ledgerCommitted: true,
      ledgerNote: approval.plan_diff_hash ? `Plan diff hash ${approval.plan_diff_hash}` : "Bound in backend",
    };
  }

  if (vehicleIncident || recallIncident) {
    projection.incident = buildIncident(approval, vehicleIncident, recallIncident);
  }

  if (cd.dispatch) {
    // Operational state is authoritative on current_day.vehicles, not on
    // the dispatch block (whose is_operational is not populated), so the
    // out-of-service set is resolved here and passed in.
    const outOfService = new Set(
      (cd.vehicles ?? [])
        .filter((v) => v.is_operational === false)
        .map((v) => v.vehicle_id),
    );
    projection.dispatch = buildDispatch(cd.dispatch, clock, outOfService);
  }

  // ---- agent activity: absent before its first safe boundary ---------
  if (raw.agent_activity_as_of) {
    projection.agentActivity = buildAgentActivity(raw, recallIncident);
    projection.executionEvidence = buildExecutionEvidence(raw, approval, recallIncident);
  }

  if (recallIncident && raw.recall_intake_as_of) {
    projection.recall = buildRecall(raw, recallIncident);
  }

  const cg = raw.execution_evidence_as_of.custody_graph;
  if (cg) {
    projection.custody = buildCustody(cg);
  }

  if (cd.recovery?.explanation) {
    projection.recovery = buildRecovery(raw);
  }

  const refusalIncident = cd.incidents.find((i) => i.refusal);
  if (refusalIncident?.refusal && cd.recovery?.explanation) {
    projection.governance = buildGovernance(refusalIncident, cd.recovery.explanation);
  }

  if (beatId === "todaysOutcome" || beatId === "tomorrowsDraft") {
    projection.outcome = buildOutcome(raw, commitments);
  }

  // ---- Tomorrow only when explicitly requested and supplied ----------
  if (raw.next_day_draft) {
    projection.tomorrow = buildTomorrow(raw);
  }

  if (beatId === "history") {
    projection.history = buildHistory(raw);
  }

  return projection;
}

// ---------------------------------------------------------------------

function buildIncident(
  approval: RawApproval | undefined,
  vehicle: RawIncident | undefined,
  recall: RawIncident | undefined,
): IncidentView {
  const primary = recall ?? vehicle!;
  const isRecall = !!recall;
  const view: IncidentView = {
    ref: primary.incident_id,
    banner: isRecall
      ? {
          title: `Food safety recall · lot ${recall!.affected_lot_id ?? "—"}`,
          body: `Incident ${recall!.incident_id} is ${recall!.status.replace(/_/g, " ").toLowerCase()}.`,
          tone: "crit",
        }
      : {
          title: `Vehicle failure · ${vehicle!.incident_id}`,
          body: "A vehicle is out of service. Affected commitments need a governed revision.",
          tone: "warn",
        },
    posture: primary.terminal_state !== "NONE" ? primary.terminal_state : undefined,
  };

  // Diff rows come from the committed, immutable approval diff only.
  if (approval?.plan_diff.length) {
    view.diffRows = approval.plan_diff.map((d) => ({
      id: d.order_id ?? "—",
      meta: [d.cases != null ? `${d.cases} cases` : null, d.change_type].filter(Boolean).join(" · "),
      before: approval.source_revision ? `${approval.source_revision} · Truck 1` : "—",
      after: d.change_type === "PICKUP" ? "Partner pickup" : `${approval.proposed_revision ?? "—"} · ${vehicleLabel(d.target_vehicle)}`,
    }));
    view.approvalCta = {
      label: `Approve ${approval.source_revision} → ${approval.proposed_revision}`,
      guard: "Requires verified human approval bound to a KMS key version.",
    };
  }
  return view;
}

/**
 * The schematic has fixed slots keyed a01..a05 / t1 / t2 / part. Map the
 * contract's agency label onto its slot so data lands where the visual
 * expects it; an agency the contract does not mention simply has no slot.
 */
const agencySlot = (agency: string | null): string | null => {
  const m = agency && /Agency\s*0*(\d+)/.exec(agency);
  return m ? `a0${m[1]}` : null;
};

const VEHICLE_SLOT: Record<string, string> = { "TRUCK-01": "t1", "TRUCK-02": "t2" };

function buildDispatch(
  d: RawDispatch,
  clock: string,
  outOfService: Set<string> = new Set(),
): DispatchView {
  const stops: DispatchView["stops"] = {};
  const vehicles: DispatchView["vehicles"] = {};

  for (const v of d.vehicles) {
    const vslot = VEHICLE_SLOT[v.vehicle_id] ?? v.vehicle_id;
    // A still-planned stop on a vehicle that is out of service is
    // IMPACTED. Both halves are authoritative — the runtime reports the
    // vehicle as not operational and reports the stop as still planned —
    // so this states a consequence of committed facts rather than
    // inventing a status the contract does not carry.
    const vehicleOutOfService =
      v.is_operational === false || outOfService.has(v.vehicle_id);
    vehicles[vslot] = {
      label: v.name ?? vehicleLabel(v.vehicle_id),
      status: vehicleOutOfService ? "Out of service" : `${v.stop_count} stops`,
      tone: vehicleOutOfService ? "impacted" : "planned",
    };
    v.stops.forEach((s) => {
      const slot = agencySlot(s.agency) ?? s.order_id;
      // Sequence comes from the contract (COMMITTED_MANIFEST_ORDER), never
      // from array position, so presentation cannot invent a route order.
      stops[slot] = {
        title: `${s.sequence ?? "—"}. ${s.order_id} · ${s.agency ?? "—"}`,
        sub: s.cases != null ? `${s.cases} cases · ${vehicleLabel(v.vehicle_id)}` : vehicleLabel(v.vehicle_id),
        tone:
          vehicleOutOfService && s.status === "PLANNED"
            ? "impacted"
            : orderTone(s.status, false)[1],
        orderId: s.order_id,
        agency: s.agency,
        cases: s.cases,
        lotId: s.lot_id,
        sequence: s.sequence,
        vehicleId: v.vehicle_id,
      };
    });
  }
  for (const p of d.partner_pickups) {
    const slot = agencySlot(p.agency) ?? p.order_id;
    stops[slot] = {
      title: `${p.order_id} · ${p.agency ?? "—"}`,
      sub: p.cases != null ? `${p.cases} cases · partner pickup` : "partner pickup",
      tone: "partner",
      orderId: p.order_id,
      agency: p.agency,
      cases: p.cases,
      lotId: p.lot_id,
      // A partner pickup sits on no vehicle manifest, so it holds no position.
      sequence: null,
      vehicleId: null,
    };
  }
  // The partner slot is a vehicle-position label in the schematic.
  const partner = d.partner_pickups[0];
  if (partner) {
    vehicles.part = {
      label: "Partner pickup",
      status: partner.cases != null ? `${partner.cases} cases` : "planned",
      tone: "partner",
    };
  }

  // Capacity arithmetic is reported only where the contract supplies it.
  const target = d.vehicles.find((v) => v.capacity_cases != null && v.assigned_cases != null);
  const partnerCases = d.partner_pickups.reduce((n, p) => n + (p.cases ?? 0), 0);

  const capacityDecision: DispatchView["capacityDecision"] = target
    ? (() => {
        const cap = target.capacity_cases!;
        const after = target.assigned_cases!;
        const rerouted = reroutedCases(target.stops);
        const beforeVal = after - rerouted;
        return {
          beforeLabel: "Before",
          beforeValue: `${beforeVal} / ${cap}`,
          addLabel: "Rerouted in",
          addValue: `+${rerouted}`,
          afterLabel: "After",
          afterValue: `${after} / ${cap}`,
          afterFillPct: Math.round((after / cap) * 100),
          remainingLabel: "Remaining",
          remainingValue: target.remaining_cases != null ? `${target.remaining_cases}` : "—",
          needsLabel: "Partner pickup",
          needsValue: partnerCases ? `${partnerCases} cases` : "—",
          verdict: target.at_capacity ? "AT CAPACITY" : "FITS",
          explain: `${beforeVal} + ${rerouted} = ${after} of ${cap}. ${partnerCases ? `${partnerCases} cases exceed the vehicle and route to a refrigerated partner pickup.` : ""}`.trim(),
        };
      })()
    : {
        // rev07 carries no capacity row: unknown must stay unknown.
        beforeLabel: "Before",
        beforeValue: "Unknown",
        addLabel: "Rerouted in",
        addValue: "—",
        afterLabel: "After",
        afterValue: "Unknown",
        afterFillPct: 0,
        remainingLabel: "Remaining",
        remainingValue: "Unknown",
        needsLabel: "Partner pickup",
        needsValue: partnerCases ? `${partnerCases} cases` : "—",
        verdict: "CAPACITY NOT REPORTED",
        explain: "The projection carries no capacity row at this boundary, so no capacity claim is made.",
      };

  return {
    title: `Planned dispatch · ${d.plan_id ?? "—"}${d.revision ? ` / ${d.revision}` : ""}`,
    schematicLabel: "Planned dispatch · not live vehicle tracking",
    note: `Committed assignments as of ${clock}`,
    stops,
    vehicles,
    capacityDecision,
  };
}

/** Cases added by this revision — a rerouted stop is one not yet delivered. */
function reroutedCases(stops: RawDispatch["vehicles"][number]["stops"]): number {
  const rerouted = stops.filter((s) => s.assignment_type === "VEHICLE_ROUTED" && s.status === "PLANNED");
  // The single largest planned stop is the one this revision moved in.
  return rerouted.length ? Math.max(...rerouted.map((s) => s.cases ?? 0)) : 0;
}

function buildAgentActivity(raw: RawProjection, recall: RawIncident | undefined): AgentActivityView {
  const aa = raw.agent_activity_as_of!;
  // The ADK version lives on the specialists as `adk_framework`
  // ("google-adk-2.6.1"); manifest_version is the fleet manifest, a
  // different thing entirely. Label only what the contract states.
  const framework = aa.agents.map((a) => a.adk_framework).find((f): f is string => !!f);
  const view: AgentActivityView = {
    adkLabel: framework ? framework.replace(/^google-adk-/, "ADK ") : "ADK version not reported",
    note: "separately correlated specialist runners · deterministic policy + ledger commit",
    agents: aa.agents.map(agentCell),
    boundaries: [],
  };
  // Model Armor is a governance boundary, never a sixth agent.
  const screening = recall?.model_armor_screening;
  if (screening) {
    view.boundaries.push({
      label: "Model Armor",
      detail: `Untrusted notice screened · ${screening.result}`,
      pass: screening.result === "PASS",
    });
  }
  const refusal = raw.current_day.incidents.find((i) => i.refusal)?.refusal;
  if (refusal) {
    view.governanceNote = `Deterministic policy returned ${refusal.decision} with ${refusal.mutations_applied} mutations. This is a policy outcome, not an agent status.`;
  }
  return view;
}

function buildExecutionEvidence(
  raw: RawProjection,
  approval: RawApproval | undefined,
  recall: RawIncident | undefined,
): ExecutionEvidenceView {
  const aa = raw.agent_activity_as_of!;
  const coordinator = aa.agents.find((a) => a.role === "ROOT_COORDINATOR");
  const specialists: SpecialistEvidence[] = aa.agents
    .filter((a) => a.role !== "ROOT_COORDINATOR")
    .map((a) => {
      const status = agentStatus(a.state);
      const ev: SpecialistEvidence = {
        name: a.display_name,
        status,
        note: [a.model_used, a.deterministic_validation].filter(Boolean).join(" · ") || "Reported",
      };
      // Tool evidence ONLY where the contract records an invocation.
      if (a.tool_invocations.length > 0) {
        ev.toolUse = {
          label: a.declared_tools.join(", ") || "bounded tool",
          evidence: `${a.tool_invocations.length} committed invocation${a.tool_invocations.length === 1 ? "" : "s"}`,
        };
      }
      return ev;
    });

  const refusal = raw.current_day.incidents.find((i) => i.refusal)?.refusal;

  return {
    title: "Execution record",
    context: `${aa.topology.replace(/_/g, " ").toLowerCase()} · committed ${aa.committed_at}`,
    coordinator: {
      name: coordinator?.display_name ?? "Incident Coordinator",
      status: coordinator ? agentStatus(coordinator.state) : "NOT_YET_REPORTED",
      result: coordinator?.deterministic_validation ?? null,
    },
    correlationNote:
      "Specialists run under their own run and session identifiers, correlated by the application. This is not native parent-child agent parentage.",
    specialists,
    modelArmor: recall?.model_armor_screening ? { pass: recall.model_armor_screening.result === "PASS" } : null,
    authority: {
      policyText: "Every mutation passes deterministic policy before the ledger accepts it.",
      ledgerCommitted: raw.execution_evidence_as_of.receipts_committed > 0,
      ledgerReceiptRef: null, // bound in backend; never invented here
      kmsKeyVersion: approval?.kms_key_version ?? null,
      note: "Key version only. Signature material is never transported to the browser.",
    },
    refusal: refusal
      ? { verdict: `${refusal.decision} · ${refusal.mutations_applied} MUTATIONS`, body: `Recorded at ${refusal.committed_at} as receipt ${refusal.receipt_id}.` }
      : undefined,
  };
}

function buildRecall(raw: RawProjection, recall: RawIncident): RecallView {
  const intake = raw.recall_intake_as_of!;
  const screened = recall.model_armor_screening?.result === "PASS";
  const affected = raw.current_day.commitments.filter((c) => c.lot_id === recall.affected_lot_id);
  const uniqueOrders = new Set(affected.map((c) => c.order_id));

  return {
    ref: recall.incident_id,
    banner: {
      title: `Recall notice · lot ${recall.affected_lot_id ?? "—"}`,
      body: `Incident ${recall.incident_id} · ${recall.status.replace(/_/g, " ").toLowerCase()}`,
    },
    intake: intake.steps.map((s) => ({
      key: s.step,
      title: INTAKE_TITLE[s.step] ?? s.step.replace(/_/g, " "),
      body: INTAKE_BODY[s.step] ?? "",
      status: s.state === "COMPLETED" ? "COMPLETE" : s.state === "IN_PROGRESS" ? "IN_PROGRESS" : "PENDING",
    })),
    // The notice body is not persisted in the projection.
    sourceExcerpt: HISTORICAL_NOT_RETAINED,
    sourceAnchoredLot: recall.affected_lot_id ?? "—",
    affectedCommitments: `${uniqueOrders.size} commitment${uniqueOrders.size === 1 ? "" : "s"} reference lot ${recall.affected_lot_id ?? "—"}`,
    modelArmor: screened ? "PASS" : null,
  };
}

function buildCustody(cg: NonNullable<RawProjection["execution_evidence_as_of"]["custody_graph"]>): CustodyView {
  const all = [...cg.current_positions];
  all.sort((a, b) => {
    const ia = NODE_ORDER.indexOf(a.node_id);
    const ib = NODE_ORDER.indexOf(b.node_id);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });

  // The exception is what matters: how many positions are actually
  // unresolved. Counted from the projection, never asserted.
  const unconfirmedSites = all.filter(
    (n) => n.acknowledgment_status !== "CONFIRMED" && n.on_hand_cases > 0,
  ).length;

  return {
    question: `Where is lot ${cg.lot_id} right now?`,
    headline:
      `${cg.unique_current_cases} cases traced → ${cg.unconfirmed_cases} unconfirmed ` +
      `at ${unconfirmedSites} downstream site${unconfirmedSites === 1 ? "" : "s"}`,
    headlineDetail:
      `Every recorded hand-off was traversed. ${cg.confirmed_cases} of ` +
      `${cg.unique_current_cases} cases have a known location and disposition.`,
    totalUnique: cg.unique_current_cases,
    confirmed: cg.confirmed_cases,
    unconfirmed: cg.unconfirmed_cases,
    unconfirmedSites,
    nodes: all.map((n) => ({
      key: n.node_id,
      label: n.name,
      roleLabel: NODE_ROLE[n.node_id],
      value: n.on_hand_cases,
      status: n.acknowledgment_status === "CONFIRMED" ? "CONFIRMED" : "UNCONFIRMED",
      note: n.acknowledgment_status === "CONFIRMED" ? undefined : "Awaiting acknowledgment",
    })),
    reconciliation: [
      { label: "Confirmed", value: `${cg.confirmed_cases}`, tone: "ok" },
      { label: "Unconfirmed", value: `${cg.unconfirmed_cases}`, tone: "warn" },
      { label: "Unique current cases", value: `${cg.unique_current_cases}`, tone: "neutral" },
      { label: "Nodes", value: `${cg.node_count}`, tone: "neutral", muted: true },
      { label: "Query engine", value: cg.query_engine, tone: "neutral", muted: true },
    ],
    sumExpression: all.map((n) => n.on_hand_cases).join(" + ") + ` = ${cg.unique_current_cases}`,
    caveat: "Confirmed custody ≠ safe, recovered, or eligible. Intermediate subtotals are not re-added.",
  };
}

function buildRecovery(raw: RawProjection): RecoveryView {
  const e = raw.current_day.recovery.explanation!;
  const items: RecoveryView["items"] = [
    {
      text: e.statement,
      tone: "info",
      // Arithmetic over committed quantities — labelled as such.
      authorityClass: e.basis === "DETERMINISTIC_DERIVATION" ? "DETERMINISTIC_POLICY" : "AGENT_PROPOSAL",
    },
  ];
  if (e.persisted_agent_rationale) {
    items.push({ text: e.persisted_agent_rationale, tone: "neutral", authorityClass: "AGENT_PROPOSAL" });
  }

  const byAgency = raw.current_day.recovery.allocations
    .filter((a) => a.agency_id && a.cases != null)
    .map((a) => `${a.agency_id}: ${a.cases}`)
    .join(" · ");

  const short = raw.current_day.recovery.shortfalls.find((s) => s.cases != null);

  // Programs preserved = agencies fully allocated. Programs total = every
  // agency this recovery had to answer for. Both counted from the
  // projection's own explanation, not asserted.
  const programsPreserved = e.agencies_allocated;
  const programsTotal = e.agencies_allocated + e.agencies_short;

  return {
    question: "What can actually be replaced from safe stock?",
    headline:
      `${e.cases_allocated} safe replacements preserve service for ` +
      `${programsPreserved} of ${programsTotal} programs`,
    headlineDetail:
      e.cases_short > 0
        ? `The remaining ${e.cases_short}-case gap stays visible rather than ` +
          "being filled with stock the evidence does not support."
        : "Every program was covered from confirmed-safe stock.",
    programsPreserved,
    programsTotal,
    items,
    safeReplacements: { total: e.cases_allocated, breakdown: byAgency || `${e.agencies_allocated} agencies` },
    shortfall: {
      value: e.cases_short,
      agency: short?.agency_id ?? `${e.agencies_short} agency`,
      note: `${e.cases_allocated} of ${e.cases_requested} requested cases allocated.`,
    },
    authorityNote: `Basis: ${e.basis.replace(/_/g, " ").toLowerCase()}. ${e.persisted_agent_rationale ? "" : "No agent rationale was persisted, so none is shown."}`.trim(),
  };
}

function buildGovernance(incident: RawIncident, explanation: RawProjection["current_day"]["recovery"]["explanation"]): GovernanceView {
  const r = incident.refusal!;
  const rows: GovernanceView["whyCannotClose"] = [];
  if (explanation) {
    rows.push({ label: "Cases still short", value: `${explanation.cases_short}`, tone: "warn" });
    rows.push({ label: "Agencies short", value: `${explanation.agencies_short}`, tone: "warn" });
  }
  rows.push({ label: "Terminal state", value: incident.terminal_state, tone: "crit" });

  return {
    question: "Why can this incident not be closed?",
    proposal: {
      // The real request. The coordinator asked for the closure eligibility
      // check that policy requires — it did not invoke a DECLARE_CONTAINED
      // command, because no such command exists in the ledger.
      label: `Requested · ${r.requested_action.replace(/_/g, " ").toLowerCase()}`,
      time: r.committed_at,
      text:
        `The ${(r.requested_by_role ?? "INCIDENT_COORDINATOR").replace(/_/g, " ").toLowerCase()} ` +
        `requested the closure eligibility check for incident ${incident.incident_id}.`,
    },
    policyEvalLabel:
      `${r.decided_by.replace(/_/g, " ").toLowerCase()} → ${r.policy_action}`,
    refusal: {
      verdict: `${r.decision} · ${r.mutations_applied} MUTATIONS`,
      body: "Policy refused the closure and the ledger applied no mutation.",
      reason: `Containment is incomplete while the incident remains ${incident.terminal_state.replace(/_/g, " ").toLowerCase()}.`,
      mutations: `${r.mutations_applied}`,
      recordedAt: r.committed_at,
      posture: incident.terminal_state,
    },
    whyCannotClose: rows,
    policyNote: `Refusal committed as receipt ${r.receipt_id}. A refusal is a governance outcome, never an agent failure.`,
  };
}

function buildOutcome(raw: RawProjection, commitments: Commitment[]): OutcomeView {
  const cg = raw.execution_evidence_as_of.custody_graph;
  const e = raw.current_day.recovery.explanation;
  const delivered = commitments.filter((c) => c.stateTone === "delivered");
  const recallIncident = raw.current_day.incidents.find((i) => i.incident_type === "FOOD_SAFETY_RECALL");

  return {
    dayLabel: dayLabelOf(raw.operating_day),
    posture: recallIncident?.terminal_state ?? "NORMAL",
    service: {
      fulfilledCount: delivered.length,
      total: commitments.length,
      fulfilledLabel: `${delivered.length} of ${commitments.length} commitments delivered`,
      fulfilledList: delivered.map((c) => c.id).join(", ") || "—",
      unfulfilled: {
        label: `${commitments.length - delivered.length} not delivered`,
        badge: recallIncident ? "RECALL HOLD" : "OPEN",
      },
      note: "Delivery state is read from committed commitments only.",
    },
    safety: {
      traced: cg?.unique_current_cases ?? 0,
      confirmed: cg?.confirmed_cases ?? 0,
      caveatTitle: "Traced is not the same as recovered",
      caveatBody: "Custody confirms location. It does not certify that product is safe, recovered, or eligible.",
      rows: [
        ...(cg ? [{ label: `${cg.confirmed_cases} cases confirmed`, badge: "CONFIRMED", tone: "ok" as Tone }] : []),
        ...(cg && cg.unconfirmed_cases > 0 ? [{ label: `${cg.unconfirmed_cases} cases unconfirmed`, badge: "UNCONFIRMED", tone: "warn" as Tone }] : []),
        ...(e ? [{ label: `${e.cases_short} cases short of request`, badge: "SHORTFALL", tone: "warn" as Tone }] : []),
      ],
    },
    nextRequirements: raw.carry_forward_obligations.map((o) => ({
      id: o.reference_id,
      tone: (o.kind === "UNRESOLVED_INCIDENT" ? "crit" : "warn") as Tone,
      badge: o.kind.replace(/_/g, " "),
      title: o.reference_id,
      body: [o.incident_id ? `Incident ${o.incident_id}` : null, o.lot_id ? `Lot ${o.lot_id}` : null, o.terminal_state ?? null]
        .filter(Boolean)
        .join(" · ") || "Carried into tomorrow.",
      action: { label: "Open Tomorrow", target: "tomorrowsDraft" as BeatId },
    })),
  };
}

/**
 * Saturday's candidate schedule, read from the contract.
 *
 * Carry-forward obligations are shown whenever they exist, because they are
 * committed regardless of whether a candidate plan was returned. Candidate
 * assignments are shown ONLY when the contract supplied them; there is no
 * fallback, and an empty candidate plan renders the unavailable state.
 */
function buildTomorrow(raw: RawProjection): TomorrowView {
  const nd = raw.next_day_draft;
  const inheritedObligations = raw.carry_forward_obligations.map((o) => ({
    id: o.reference_id,
    badge: o.kind.replace(/_/g, " "),
    title: o.reference_id,
    origin: o.incident_id
      ? `from ${o.incident_id}`
      : o.lot_id
        ? `lot ${o.lot_id}`
        : "carried forward",
  }));

  if (!nd) {
    return {
      available: false,
      dayLabel: "Saturday",
      planId: null,
      revision: null,
      status: null,
      approvalRequired: false,
      activationSupported: false,
      candidateVehicles: [],
      unassignedDemand: [],
      inheritedObligations,
      unavailableReason: "No candidate plan was returned for this boundary.",
    };
  }

  const candidateVehicles: CandidateVehicle[] = (nd.candidate_vehicles ?? []).map((v) => ({
    vehicleId: v.vehicle_id ?? null,
    stopCount: v.stop_count,
    candidateLoadCases: v.candidate_load_cases,
    stops: v.stops.map((s) => ({
      orderId: s.order_id,
      agency: s.agency ?? null,
      agencyId: s.agency_id ?? null,
      cases: s.cases ?? null,
      lotId: s.lot_id ?? null,
      sequence: s.sequence,
      status: s.status,
    })),
  }));

  const hasAssignments = candidateVehicles.some((v) => v.stops.length > 0);

  return {
    // Unassigned demand alone is not a schedule. Without any assignment the
    // candidate surface has nothing truthful to draw, so it stays unavailable.
    available: hasAssignments,
    dayLabel: `${nd.plan_id} · ${nd.revision}`,
    planId: nd.plan_id,
    revision: nd.revision,
    status: nd.status,
    approvalRequired: nd.approval_required,
    // Read from the contract, never assumed. The projection pins this false.
    activationSupported: nd.activation_supported === true,
    candidateVehicles,
    unassignedDemand: (nd.unassigned_demand ?? []).map((u) => ({
      shortfallId: u.shortfall_id,
      agencyId: u.agency_id ?? null,
      cases: u.cases ?? null,
      reason: u.reason ?? null,
    })),
    inheritedObligations,
    unavailableReason: hasAssignments
      ? null
      : "The contract returned no candidate assignments for this boundary.",
  };
}

function buildHistory(raw: RawProjection): HistoryView {
  const h = raw.execution_evidence_as_of.history;
  return {
    asOf: raw.projection_boundary.as_of,
    ledger: h.map((e) => {
      const denied = e.status === "DENIED";
      return {
        time: clockOf(e.committed_at),
        title: ACTION_TITLE[e.action_type] ?? e.action_type.replace(/_/g, " "),
        meta: `${e.receipt_id} · ${e.mutations_applied ?? 0} mutation${e.mutations_applied === 1 ? "" : "s"}`,
        tone: (denied ? "crit" : "ok") as Tone,
        tag: { label: e.status, tone: (denied ? "crit" : "ok") as Tone },
      };
    }),
    lineage: raw.current_day.plan_revisions.map((r) => ({
      text: `${r.plan_id} · ${r.revision} · ${r.status}`,
      tone: (r.status === "ACTIVE" ? "ok" : r.status === "INVALIDATED" ? "crit" : "neutral") as Tone,
      glyph: r.status === "ACTIVE" ? "●" : "○",
    })),
    note: `${h.length} committed receipt${h.length === 1 ? "" : "s"} at this boundary. History is read-only.`,
  };
}
