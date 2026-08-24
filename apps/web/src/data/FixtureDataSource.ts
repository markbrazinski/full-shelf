// =====================================================================
// NON-RUNTIME REFERENCE MATERIAL — NOT A DATA SOURCE FOR THE APP
// ---------------------------------------------------------------------
// Preserved Design-handoff reference. It holds hardcoded scenario
// quantities, IDs, agent results, receipts and timestamps that are NOT
// backed by the accepted backend contract, and several of them are now
// known to contradict it.
//
// The runtime reads accepted contract v2 over HTTP through
// data/ProjectionHttpDataSource.ts, selected in env.ts. Nothing on the
// runtime entry path (main.tsx → App.tsx) imports this module, and it
// is absent from the production bundle.
//
// Permitted uses: tests, isolated component development, handoff
// reference. Never re-bind this as an application data source.
// =====================================================================
// =====================================================================
// Full Shelf — DETERMINISTIC fixture data-source (SYNTHETIC_TEST)
// ---------------------------------------------------------------------
// The ONLY module that holds canonical scenario quantities, IDs, agent
// results, receipts, and timestamps. Presentation reads projections and
// contains none of these constants. Swap this for a live
// FullShelfDataSource (OBSERVED_LIVE / RECORDED_LIVE) with no component
// changes. Every projection reports dataMode SYNTHETIC_TEST, which forces
// the visible DETERMINISTIC TEST MODE banner.
// =====================================================================

import type { FullShelfDataSource } from "./FullShelfDataSource";
import {
  HISTORICAL_NOT_RETAINED,
  type AgentCell,
  type AgentDisplayStatus,
  type BeatId,
  type BeatMeta,
  type Commitment,
  type FullShelfProjection,
  type OrderStateTone,
} from "../types/fullShelf";

export { HISTORICAL_NOT_RETAINED };
export const DATA_MODE = "SYNTHETIC_TEST" as const;

export const BEATS: BeatMeta[] = [
  { id: "healthy", time: "08:05", label: "Healthy" },
  { id: "truckFailure", time: "08:20", label: "Truck failure" },
  { id: "revisionReview", time: "08:20", label: "Revision review" },
  { id: "dispatchSchematic", time: "08:20", label: "Dispatch schematic" },
  { id: "rev08Active", time: "08:24", label: "rev08 active" },
  { id: "recallReceived", time: "09:35", label: "Recall received" },
  { id: "recallProcessing", time: "09:36", label: "Recall processing" },
  { id: "custodyEstablished", time: "10:05", label: "Custody established" },
  { id: "governedRecovery", time: "10:10", label: "Governed recovery" },
  { id: "governanceRefusal", time: "10:12", label: "Governance refusal" },
  { id: "todaysOutcome", time: "16:30", label: "Today's outcome" },
  { id: "tomorrowsDraft", time: "17:00", label: "Tomorrow's draft" },
  { id: "history", time: "—", label: "History" },
];

const DATE = "Fri · Aug 14";

// ---- commitment factory (facts only) --------------------------------
const cm = (
  id: string,
  lot: string,
  agency: string,
  cases: number,
  vehicle: string,
  stateLabel: string,
  stateTone: OrderStateTone,
  lotFlagged = false,
): Commitment => ({ id, lot, agency, cases, vehicle, stateLabel, stateTone, lotFlagged });

const REV07: Commitment[] = [
  cm("O201", "LTC-4471", "Agency 01", 18, "Truck 1", "Delivered", "delivered"),
  cm("O202", "LTC-4471", "Agency 02", 22, "Truck 1", "Planned", "planned"),
  cm("O203", "LTC-4471", "Agency 03", 20, "Truck 1", "Planned", "planned"),
  cm("O204", "LTC-5090", "Agency 04", 15, "Truck 2", "Planned", "planned"),
  cm("O205", "LTC-5090", "Agency 05", 21, "Truck 2", "Planned", "planned"),
];

// ---- five-agent fleet helpers ---------------------------------------
const AG_NAMES: Record<string, string> = {
  coord: "Incident Coordinator",
  recall: "Recall Extraction",
  net: "Network & Custody",
  fulf: "Fulfillment & Recovery",
  part: "Partner Operations",
};

type AgentTriple = [AgentDisplayStatus, string, string | null];

const agent = (key: string, isCoordinator: boolean, [status, task, result]: AgentTriple): AgentCell => ({
  key,
  name: AG_NAMES[key],
  isCoordinator,
  status,
  task,
  result: result ?? null,
});

const NR: AgentDisplayStatus = "NOT_YET_REPORTED";
const NI: AgentDisplayStatus = "NOT_INVOLVED";
const OK: AgentDisplayStatus = "COMPLETED";

// truck-failure recovery fleet (recall agent not involved)
const FLEET_RECOVERY = {
  adkLabel: "ADK 2.6.1",
  note: "agents propose & use bounded tools · deterministic policy + ledger commit",
  agents: [
    agent("coord", true, [OK, "Coordinate truck-failure response", "Coordination complete · rev08 proposed"]),
    agent("recall", false, [NI, "Extract recall facts", null]),
    agent("net", false, [OK, "Check Truck 2 capacity & routing", "O202 fits · Truck 2 → 58 / 60"]),
    agent("fulf", false, [OK, "Propose feasible recovery", "O202 to Truck 2 · O203 to partner"]),
    agent("part", false, [OK, "Propose refrigerated pickup", "Partner path proposed for O203"]),
  ],
  boundaries: [],
};

interface FleetRecallOpts {
  coord: AgentTriple;
  recall: AgentTriple;
  net: AgentTriple;
  fulf: AgentTriple;
  part: AgentTriple;
  armorPass: boolean;
  governanceNote?: string;
}

const fleetRecall = (opts: FleetRecallOpts) => ({
  adkLabel: "ADK 2.6.1",
  note: "agents propose & use bounded tools · deterministic policy + ledger commit",
  agents: [
    agent("coord", true, opts.coord),
    agent("recall", false, opts.recall),
    agent("net", false, opts.net),
    agent("fulf", false, opts.fulf),
    agent("part", false, opts.part),
  ],
  boundaries: opts.armorPass
    ? [
        {
          label: "Model Armor · recall input screening",
          detail: "Applied to the inbound recall notice before extraction.",
          pass: true,
        },
      ]
    : [],
  governanceNote: opts.governanceNote,
});

// ---- execution evidence helpers -------------------------------------
const netToolUse = {
  label: "custody reconstruction",
  evidence: "traced 96 unique cases across recorded hand-offs",
};

const authorityBlock = (opts: { ledgerCommitted?: boolean; kmsKeyVersion?: string | null; note?: string }) => ({
  policyText:
    "Policy and the private ledger retain exclusive mutation authority. Agents propose; they do not mutate.",
  ledgerCommitted: !!opts.ledgerCommitted,
  ledgerReceiptRef: null as string | null, // never invented — bound by backend
  kmsKeyVersion: opts.kmsKeyVersion ?? null,
  note: opts.note ?? "In SYNTHETIC_TEST mode, live references are withheld and bound by the backend adapter.",
});

// =====================================================================
// PROJECTIONS — one per beat (partial; shell fields added by withShell)
// =====================================================================
type PartialProjection = Omit<
  FullShelfProjection,
  "beatId" | "asOf" | "dataMode" | "incidentSummary"
> & {
  currentDay: FullShelfProjection["currentDay"] & { dayLabelOverride?: string };
  // Reference material only; withShell supplies an empty summary. The runtime
  // derives this from the contract's incidents, never from a fixture.
  incidentSummary?: FullShelfProjection["incidentSummary"];
};

const P: Record<BeatId, PartialProjection> = {} as Record<BeatId, PartialProjection>;

// 1 · HEALTHY — establishes five rev07 commitments (NO capacity panel)
P.healthy = {
  currentDay: {
    clock: "",
    operatingDate: "",
    dayLabel: DATE,
    connection: "CONNECTED",
    inDaybook: true,
    posture: "NORMAL",
    authRev: "rev07",
    authPill: { label: "ACTIVE · APPROVED", tone: "ok", glyph: "●" },
    openObligations: { count: 0, note: "none open", tone: "ok" },
    needsAttention: {
      tone: "ok",
      kicker: "NEEDS ATTENTION",
      incident: "",
      title: "Nothing requires your attention",
      body: "Ordinary operating day. Five commitments approved and active under rev07.",
    },
    commitmentsSummary: { label: "5 planned · rev07", tone: "neutral" },
    commitments: REV07,
    obligationsNote: "None carried into today.",
    recentActivity: [
      { glyphTone: "ok", title: "O201 delivered · Agency 01", meta: "08:05" },
      { glyphTone: "ok", title: "rev07 approved & activated", meta: "06:45 human approval · active 07:30" },
    ],
  },
  omittedFields: [
    "incident",
    "recall",
    "custody",
    "recovery",
    "governance",
    "outcome",
    "tomorrow",
    "executionEvidence",
  ],
};

// 2 · TRUCK FAILURE
P.truckFailure = {
  currentDay: {
    clock: "",
    operatingDate: "",
    dayLabel: DATE,
    connection: "MONITORING",
    inDaybook: true,
    posture: "INTERVENTION",
    authRev: "rev07",
    authPill: { label: "ACTIVE · rev08 PROPOSED", tone: "ok", glyph: "●" },
    openObligations: { count: 1, note: "incident open", tone: "warn" },
    needsAttention: {
      tone: "warn",
      kicker: "NEEDS ATTENTION · 1",
      incident: "· INC-2210 · 08:20",
      title: "Truck 1 refrigeration failure",
      body: "O202 and O203 can no longer stay cold on Truck 1. A recovery revision (rev08) is ready for your review.",
      action: { label: "Review proposed rev08 →", target: "revisionReview" },
    },
    commitmentsSummary: { label: "2 impacted · rev07 active", tone: "warn" },
    commitments: [
      cm("O201", "LTC-4471", "Agency 01", 18, "Truck 1", "Delivered", "delivered"),
      cm("O202", "LTC-4471", "Agency 02", 22, "Truck 1", "Impacted by INC-2210", "impacted"),
      cm("O203", "LTC-4471", "Agency 03", 20, "Truck 1", "Impacted by INC-2210", "impacted"),
      cm("O204", "LTC-5090", "Agency 04", 15, "Truck 2", "Planned", "planned"),
      cm("O205", "LTC-5090", "Agency 05", 21, "Truck 2", "Planned", "planned"),
    ],
    affectedPanel: {
      kicker: "AFFECTED COMMITMENTS",
      tone: "warn",
      lines: [
        "▲ O202 · Agency 02 · 22 cases · cold chain impacted",
        "▲ O203 · Agency 03 · 20 cases · cold chain impacted",
        "● O201 already delivered · 08:05",
      ],
    },
    capacity: {
      title: "TRUCK 2 SPARE CAPACITY",
      assignedLabel: "36 / 60 assigned",
      fillPct: 60,
      spareLabel: "24 spare",
      note: "recovery load is 42",
    },
    recentActivity: [
      { glyphTone: "warn", title: "Truck 1 refrigeration failure detected", meta: "08:20 · incident INC-2210 opened" },
    ],
  },
  incident: {
    ref: "INC-2210",
    banner: {
      tone: "warn",
      title: "Truck 1 refrigeration failure",
      body: "Affects O202 and O203. O201 delivered 08:05.",
    },
  },
  agentActivity: FLEET_RECOVERY,
  executionEvidence: {
    title: "Truck-failure recovery",
    context: "Incident INC-2210",
    coordinator: { name: AG_NAMES.coord, status: OK, result: "Coordination complete · rev08 proposed" },
    correlationNote:
      "Specialist executions run in separately correlated Runner/session executions governed by the coordinator — application-managed correlation, not native ADK parent-child lineage.",
    specialists: [
      { name: AG_NAMES.recall, status: NI, note: "Not involved in this incident." },
      {
        name: AG_NAMES.net,
        status: OK,
        note: "O202 fits · Truck 2 → 58 / 60",
        toolUse: { label: "capacity check", evidence: "evaluated Truck 2 spare capacity against recovery load 42" },
      },
      { name: AG_NAMES.fulf, status: OK, note: "O202 to Truck 2 · O203 to partner" },
      { name: AG_NAMES.part, status: OK, note: "Partner pickup path proposed for O203" },
    ],
    modelArmor: null,
    authority: authorityBlock({
      ledgerCommitted: false,
      note: "rev08 is advisory until a human approves; nothing is committed here.",
    }),
  },
  omittedFields: ["recall", "custody", "recovery", "governance", "outcome", "tomorrow"],
};

// 3 · REVISION REVIEW
P.revisionReview = {
  currentDay: { clock: "", operatingDate: "", dayLabel: DATE, connection: "MONITORING", inDaybook: false },
  incident: {
    ref: "INC-2210",
    banner: {
      tone: "warn",
      title: "Truck 1 refrigeration failure · INC-2210 · 08:20",
      body: "Affects O202 and O203. O201 already delivered at 08:05. A recovery revision is proposed below.",
    },
    diffRows: [
      {
        id: "O202",
        meta: "Agency 02 · 22 cases · lot LTC-4471",
        before: "Truck 1 · refrigerated",
        after: "Truck 2 · absorbs 22 (58 / 60)",
      },
      {
        id: "O203",
        meta: "Agency 03 · 20 cases · lot LTC-4471",
        before: "Truck 1 · refrigerated",
        after: "Refrigerated partner pickup",
      },
    ],
    rationale: {
      observation: "Truck 1 can no longer protect refrigerated loads.",
      constraints:
        "O202 and O203 cannot wait without violating cold-chain requirements. Moving both to Truck 2 would exceed its 24-case spare capacity (needs 42).",
      feasibleOption:
        "Truck 2 absorbs O202 (22 cases → 58/60). O203 (20 cases) becomes a refrigerated partner pickup.",
      requiredAuthority:
        "A human must approve the complete rev07 → rev08 change before it becomes authoritative.",
    },
    unaffectedNote: "Unaffected: O204, O205 (lot LTC-5090, Truck 2, safe) remain as planned.",
    approvalCta: {
      label: "Approve rev07 → rev08",
      guard:
        "Nothing changes until you approve. The proposal is advisory; deterministic policy and the ledger hold mutation authority.",
    },
  },
  agentActivity: FLEET_RECOVERY,
  omittedFields: ["recall", "custody", "recovery", "governance", "outcome", "tomorrow"],
};
P.revisionReview.executionEvidence = { ...P.truckFailure.executionEvidence!, title: "rev08 recovery proposal" };

// 4 · DISPATCH SCHEMATIC (no GPS / positions / bearings / last-reported)
P.dispatchSchematic = {
  currentDay: { clock: "", operatingDate: "", dayLabel: DATE, connection: "MONITORING", inDaybook: false },
  incident: { ref: "INC-2210", banner: { tone: "warn", title: "Dispatch feasibility · 08:20", body: "" } },
  dispatch: {
    title: "Which recovery movement fits available capacity?",
    schematicLabel: "Dispatch schematic · not live GPS",
    note: "A schematic of committed assignments — not live positions, bearings, or GPS. Approval still happens in the plan diff.",
    stops: {
      a01: { title: "Agency 01", sub: "O201 · delivered", tone: "delivered", orderId: "O201", agency: "Agency 01", cases: 18, lotId: "LTC-4471", sequence: 1, vehicleId: "TRUCK-01" },
      a02: { title: "Agency 02", sub: "O202 · next stop", tone: "reassigned", orderId: "O202", agency: "Agency 02", cases: 22, lotId: "LTC-4471", sequence: 1, vehicleId: "TRUCK-02" },
      a03: { title: "Agency 03", sub: "O203 · partner", tone: "partner", orderId: "O203", agency: "Agency 03", cases: 20, lotId: "LTC-4471", sequence: null, vehicleId: null },
      a04: { title: "Agency 04", sub: "O204 · Truck 2", tone: "planned", orderId: "O204", agency: "Agency 04", cases: 15, lotId: "LTC-5090", sequence: 2, vehicleId: "TRUCK-02" },
      a05: { title: "Agency 05", sub: "O205 · Truck 2", tone: "planned", orderId: "O205", agency: "Agency 05", cases: 21, lotId: "LTC-5090", sequence: 3, vehicleId: "TRUCK-02" },
    },
    vehicles: {
      t1: { label: "Truck 1", status: "Failed · refrigerated load unprotected", tone: "impacted" },
      t2: { label: "Truck 2", status: "Assigned · O202, O204, O205", tone: "reassigned" },
      part: { label: "Partner", status: "Proposed · O203 · 20 refrigerated", tone: "partner" },
    },
    capacityDecision: {
      beforeLabel: "Truck 2 before",
      beforeValue: "36 / 60",
      addLabel: "Add O202",
      addValue: "+22",
      afterLabel: "Truck 2 after",
      afterValue: "58 / 60",
      afterFillPct: 97,
      remainingLabel: "Remaining capacity",
      remainingValue: "2",
      needsLabel: "O203 needs",
      needsValue: "20",
      verdict: "■ O203 DOES NOT FIT",
      explain:
        "Recovery load is 42 cases (O202 22 + O203 20). With only 2 spare after O202, O203's 20 cases become a refrigerated partner pickup instead.",
    },
  },
  agentActivity: FLEET_RECOVERY,
  omittedFields: ["recall", "custody", "recovery", "governance", "outcome", "tomorrow", "executionEvidence"],
};

// 5 · rev08 ACTIVE
P.rev08Active = {
  currentDay: {
    clock: "",
    operatingDate: "",
    dayLabel: DATE,
    connection: "CONNECTED",
    inDaybook: true,
    posture: "NORMAL",
    authRev: "rev08",
    authPill: { label: "ACTIVE · APPROVED", tone: "ok", glyph: "●" },
    openObligations: { count: 0, note: "none open", tone: "ok" },
    needsAttention: {
      tone: "ok",
      kicker: "RESOLVED",
      incident: "· INC-2210 · 08:24",
      title: "rev08 approved and active",
      body: "Recovery for the truck-failure incident is complete. The control plane continues monitoring the day.",
    },
    commitmentsSummary: { label: "rev08 active", tone: "neutral" },
    commitments: [
      cm("O201", "LTC-4471", "Agency 01", 18, "Truck 1", "Delivered", "delivered"),
      cm("O202", "LTC-4471", "Agency 02", 22, "Truck 2 (moved)", "Reassigned", "reassigned"),
      cm("O203", "LTC-4471", "Agency 03", 20, "Partner pickup", "Partner pickup", "partner"),
      cm("O204", "LTC-5090", "Agency 04", 15, "Truck 2", "Planned", "planned"),
      cm("O205", "LTC-5090", "Agency 05", 21, "Truck 2", "Planned", "planned"),
    ],
    approvalRecord: {
      decision: "Human approval",
      approver: "M. Ortega",
      role: "Ops Director",
      timestamp: "08:24 · Fri Aug 14",
      kmsKeyVersion: "key version 4", // version reference, never a signature
      kmsNote: "Verification reference · signature binds in backend",
      ledgerCommitted: true,
      ledgerNote: "Committed · receipt reference bound in backend",
    },
    obligationsNote: "None. rev08 fully covers the five commitments.",
    recentActivity: [
      { glyphTone: "ok", title: "rev08 approved & activated", meta: "08:24 · supersedes rev07" },
      { glyphTone: "neutral", title: "rev07 superseded", meta: "08:24" },
    ],
  },
  omittedFields: ["recall", "custody", "recovery", "governance", "outcome", "tomorrow", "executionEvidence"],
};

// 6 · RECALL RECEIVED (screening NOT finished → no Model Armor PASS yet)
P.recallReceived = {
  currentDay: {
    clock: "",
    operatingDate: "",
    dayLabel: DATE,
    connection: "MONITORING",
    inDaybook: true,
    posture: "RECALL",
    authRev: "rev08",
    authPill: { label: "UNDER RECALL REVIEW", tone: "crit", glyph: "■" },
    openObligations: { count: 1, note: "incident open", tone: "crit" },
    needsAttention: {
      tone: "crit",
      kicker: "NEEDS ATTENTION · 1",
      incident: "· INC-2231 · 09:35",
      title: "Recall received for lot LTC-4471",
      body: "A recall notice may invalidate the active plan. Open the recall workspace to screen the notice and reconstruct custody.",
      action: { label: "Open recall workspace →", target: "recallProcessing" },
    },
    commitmentsSummary: { label: "2 under recall review", tone: "crit" },
    commitments: [
      cm("O201", "LTC-4471", "Agency 01", 18, "delivered", "Recall review", "recall", true),
      cm("O202", "LTC-4471", "Agency 02", 22, "Truck 2", "Recall review", "recall", true),
      cm("O203", "LTC-4471", "Agency 03", 20, "Partner pickup", "Recall review", "recall", true),
      cm("O204", "LTC-5090", "Agency 04", 15, "Truck 2", "Planned", "planned"),
      cm("O205", "LTC-5090", "Agency 05", 21, "Truck 2", "Planned", "planned"),
    ],
    recallNoticePanel: {
      kicker: "RECALL NOTICE RECEIVED",
      tone: "crit",
      lines: [
        "A supplier recall notice naming lot LTC-4471 arrived at 09:35.",
        "Validity of the active plan is under review. Screening has not completed. No plan changes are committed yet.",
      ],
    },
    recentActivity: [
      { glyphTone: "crit", title: "Recall notice received · LTC-4471", meta: "09:35 · incident INC-2231 opened" },
    ],
  },
  recall: {
    ref: "INC-2231",
    banner: { title: "Recall received for lot LTC-4471", body: "Received 09:35. Screening not yet complete." },
    intake: [
      { key: "received", title: "Received", body: "Supplier recall notice for lot LTC-4471 accepted at 09:35.", status: "COMPLETE" },
      { key: "screened", title: "Screened", body: "Model Armor input screening of the inbound notice.", status: "IN_PROGRESS" },
      { key: "extracted", title: "Extracted", body: "Source-anchored extraction of lot and affected commitments.", status: "PENDING" },
      { key: "invalid", title: "Plan invalidated", body: "Pending screening + extraction.", status: "PENDING" },
      { key: "custody", title: "Reconstruct custody", body: "Pending.", status: "PENDING" },
    ],
    sourceExcerpt:
      '"CLASS II VOLUNTARY RECALL — refrigerated lot LTC-4471, all cases. Cease distribution. Isolate remaining inventory pending disposition."',
    sourceAnchoredLot: "LTC-4471",
    affectedCommitments: HISTORICAL_NOT_RETAINED, // not extracted yet
    modelArmor: null, // PASS not shown before screening completes
  },
  agentActivity: fleetRecall({
    coord: [NR, "Coordinate recall response", null],
    recall: [NR, "Extract recall facts", null],
    net: [NR, "Reconstruct custody", null],
    fulf: [NR, "Produce recovery proposal", null],
    part: [NR, "Propose partner action", null],
    armorPass: false,
  }),
  omittedFields: [
    "custody",
    "recovery",
    "governance",
    "outcome",
    "tomorrow",
    "executionEvidence",
    "recall.affectedCommitments",
    "recall.modelArmor",
  ],
};

// 7 · RECALL PROCESSING (screening complete → Model Armor PASS appears)
P.recallProcessing = {
  currentDay: { clock: "", operatingDate: "", dayLabel: DATE, connection: "MONITORING", inDaybook: false },
  recall: {
    ref: "INC-2231",
    banner: {
      title: "What changed, and is the previously approved plan still valid?",
      body: "Recall INC-2231 · lot LTC-4471 · received 09:35. Intake is running now.",
    },
    intake: [
      { key: "received", title: "Received", body: "Supplier recall notice for lot LTC-4471 accepted at 09:35.", status: "COMPLETE" },
      { key: "screened", title: "Screened", body: "Model Armor input screening of the inbound notice — PASS.", status: "COMPLETE" },
      { key: "extracted", title: "Extracted", body: "Source-anchored extraction of lot LTC-4471 and affected commitments O202, O203.", status: "COMPLETE" },
      { key: "invalid", title: "Plan invalidated", body: "rev08 assumptions falsified; lot-level movement barrier committed.", status: "COMPLETE" },
      { key: "custody", title: "Reconstructing custody", body: "Tracing unique cases of LTC-4471 across custody. In progress while the workspace is open.", status: "IN_PROGRESS" },
    ],
    sourceExcerpt:
      '"CLASS II VOLUNTARY RECALL — refrigerated lot LTC-4471, all cases. Cease distribution. Isolate remaining inventory pending disposition."',
    sourceAnchoredLot: "LTC-4471",
    affectedCommitments: "O202 · O203",
    modelArmor: "PASS", // shown only after screening completes
    invalidation: {
      title: "PLAN INVALIDATED",
      body: "rev08's affected assumptions are now false. A lot-level movement barrier is committed; custody reconstruction is in progress. Open Custody impact when it completes.",
    },
  },
  agentActivity: fleetRecall({
    coord: [NR, "Coordinate recall response", null],
    recall: [OK, "Extract recall facts", "Lot LTC-4471 · O202, O203 affected"],
    net: [NR, "Reconstruct custody", null],
    fulf: [NR, "Produce recovery proposal", null],
    part: [NR, "Propose partner action", null],
    armorPass: true,
  }),
  executionEvidence: {
    title: "Recall response",
    context: "Incident INC-2231 · lot LTC-4471",
    coordinator: { name: AG_NAMES.coord, status: NR, result: null },
    correlationNote:
      "Specialist executions run in separately correlated Runner/session executions governed by the coordinator — application-managed correlation, not native ADK parent-child lineage.",
    specialists: [
      { name: AG_NAMES.recall, status: OK, note: "Lot LTC-4471 · O202, O203 affected" },
      { name: AG_NAMES.net, status: NR, note: "Not yet reported" },
      { name: AG_NAMES.fulf, status: NR, note: "Not yet reported" },
      { name: AG_NAMES.part, status: NR, note: "Not yet reported" },
    ],
    modelArmor: { pass: true },
    authority: authorityBlock({
      ledgerCommitted: true,
      note: "Movement barrier committed by policy. Live references bound by the backend adapter.",
    }),
  },
  omittedFields: ["custody", "recovery", "governance", "outcome", "tomorrow"],
};

// 8 · CUSTODY ESTABLISHED
P.custodyEstablished = {
  currentDay: { clock: "", operatingDate: "", dayLabel: DATE, connection: "MONITORING", inDaybook: false },
  incident: { ref: "INC-2231", banner: { tone: "warn", title: "Recall INC-2231 · lot LTC-4471", body: "" }, posture: "PARTIALLY_CONTAINED" },
  custody: {
    question: "Where did lot LTC-4471 move?",
    totalUnique: 96,
    nodes: [
      { key: "wh", label: "Warehouse", value: 24, status: "CONFIRMED" },
      { key: "t2", label: "Truck 2 · O202", value: 22, status: "BLOCKED" },
      { key: "part", label: "Partner · O203", value: 20, status: "BLOCKED" },
      { key: "dr", label: "Direct rescue", value: 12, status: "CONFIRMED" },
      { key: "a01", label: "Agency 01 · retains", value: 10, status: "CONFIRMED" },
      { key: "s01", label: "Site 01", value: 8, status: "UNCONFIRMED", note: "forwarded from Agency 01" },
    ],
    reconciliation: [
      { label: "Warehouse", value: "24", tone: "neutral" },
      { label: "Truck 2 · O202", value: "22", tone: "neutral" },
      { label: "Partner-pickup · O203", value: "20", tone: "neutral" },
      { label: "Direct rescue allocation", value: "12", tone: "neutral" },
      { label: "Agency 01 · retains", value: "10", tone: "neutral" },
      { label: "Site 01 · forwarded subset", value: "8", tone: "warn" },
      { label: "O201 delivered · 18 (= 10 + 8, not re-added)", value: "—", tone: "neutral", muted: true },
    ],
    sumExpression: "24 + 22 + 20 + 12 + 10 + 8 = 96",
    caveat: "Confirmed custody ≠ safe, recovered, or eligible.",
  },
  agentActivity: fleetRecall({
    coord: [NR, "Coordinate response", null],
    recall: [OK, "Extract recall facts", "Lot LTC-4471 · O202, O203 affected"],
    net: [OK, "Reconstruct custody", "96 unique · 88 confirmed · 8 unconfirmed"],
    fulf: [NR, "Produce recovery proposal", null],
    part: [NR, "Propose partner action", null],
    armorPass: true,
  }),
  executionEvidence: {
    title: "Custody reconstruction",
    context: "Incident INC-2231 · lot LTC-4471",
    coordinator: { name: AG_NAMES.coord, status: NR, result: null },
    correlationNote:
      "Specialist executions run in separately correlated Runner/session executions governed by the coordinator — application-managed correlation, not native ADK parent-child lineage.",
    specialists: [
      { name: AG_NAMES.recall, status: OK, note: "Lot LTC-4471 · O202, O203 affected" },
      { name: AG_NAMES.net, status: OK, note: "96 unique · 88 confirmed · 8 unconfirmed", toolUse: netToolUse },
      { name: AG_NAMES.fulf, status: NR, note: "Not yet reported" },
      { name: AG_NAMES.part, status: NR, note: "Not yet reported" },
    ],
    modelArmor: { pass: true },
    authority: authorityBlock({ ledgerCommitted: true }),
  },
  omittedFields: ["recovery", "governance", "outcome", "tomorrow"],
};

// 9 · GOVERNED RECOVERY
P.governedRecovery = {
  currentDay: { clock: "", operatingDate: "", dayLabel: DATE, connection: "MONITORING", inDaybook: false },
  incident: { ref: "INC-2231", banner: { tone: "warn", title: "Recall INC-2231 · lot LTC-4471", body: "" }, posture: "PARTIALLY_CONTAINED" },
  recovery: {
    question: "What is being done, and who authorized it?",
    items: [
      { text: "Lot-level movement barrier active for LTC-4471", tone: "crit", authorityClass: "DETERMINISTIC_POLICY" },
      { text: "Affected movement (O202, O203) held / stopped", tone: "crit", authorityClass: "COMMITTED_LEDGER" },
      { text: "Partner pickup path proposed for O203", tone: "info", authorityClass: "AGENT_PROPOSAL" },
      { text: "40 cases replaced safely — Agency 01: 18 · Agency 02: 22", tone: "ok", authorityClass: "CONFIRMED" },
      { text: "Agency 03 truthful 20-case shortfall remains", tone: "warn", authorityClass: "OPEN" },
      { text: "Site 01 obligation open — 8 cases unconfirmed", tone: "warn", authorityClass: "OPEN" },
    ],
    safeReplacements: { total: 40, breakdown: "Agency 01 receives 18 · Agency 02 receives 22." },
    shortfall: { value: 20, agency: "Agency 03", note: "Not resolved. Remains visible and carries forward as an obligation." },
    authorityNote:
      "Authority classes: agent proposal · deterministic policy · committed ledger · physically confirmed. Agents propose; policy and the ledger commit.",
  },
  agentActivity: fleetRecall({
    coord: [OK, "Reconcile specialist outputs", "Coordination complete"],
    recall: [OK, "Extract recall facts", "Lot LTC-4471 · O202, O203 affected"],
    net: [OK, "Reconstruct custody", "96 unique · 88 confirmed · 8 unconfirmed"],
    fulf: [OK, "Produce recovery proposal", "40 replaced · Agency 03 short 20"],
    part: [OK, "Propose partner action", "Partner pickup for O203"],
    armorPass: true,
  }),
  executionEvidence: {
    title: "Governed recovery",
    context: "Incident INC-2231 · lot LTC-4471",
    coordinator: { name: AG_NAMES.coord, status: OK, result: "Coordination complete" },
    correlationNote:
      "Specialist executions run in separately correlated Runner/session executions governed by the coordinator — application-managed correlation, not native ADK parent-child lineage.",
    specialists: [
      { name: AG_NAMES.recall, status: OK, note: "Lot LTC-4471 · O202, O203 affected" },
      { name: AG_NAMES.net, status: OK, note: "96 unique · 88 confirmed · 8 unconfirmed", toolUse: netToolUse },
      { name: AG_NAMES.fulf, status: OK, note: "40 replaced · Agency 03 short 20" },
      { name: AG_NAMES.part, status: OK, note: "Partner pickup for O203" },
    ],
    modelArmor: { pass: true },
    authority: authorityBlock({ ledgerCommitted: true }),
  },
  omittedFields: ["governance", "outcome", "tomorrow"],
};

// 10 · GOVERNANCE REFUSAL (climax)
P.governanceRefusal = {
  currentDay: { clock: "", operatingDate: "", dayLabel: DATE, connection: "MONITORING", inDaybook: false },
  incident: { ref: "INC-2231", banner: { tone: "warn", title: "Recall INC-2231 · lot LTC-4471", body: "" }, posture: "PARTIALLY_CONTAINED" },
  governance: {
    question: "Can the incident be declared contained?",
    proposal: {
      label: "AGENT PROPOSAL · 10:12",
      time: "10:12",
      text: "Incident Coordinator proposed DECLARE_CONTAINED for INC-2231, to close the incident.",
    },
    policyEvalLabel: "DETERMINISTIC POLICY EVALUATION",
    refusal: {
      verdict: "DENIED · 0 MUTATIONS",
      body: "Policy refused the proposal. Eight Site 01 cases remain unconfirmed, so complete containment cannot be asserted. No state was mutated; the incident remains PARTIALLY_CONTAINED.",
      reason: "8 unconfirmed cases",
      mutations: "0",
      recordedAt: "10:12 · authoritative",
      posture: "PARTIALLY_CONTAINED",
    },
    whyCannotClose: [
      { label: "Cases traced", value: "96", tone: "neutral" },
      { label: "Confirmed custody", value: "88", tone: "ok" },
      { label: "Site 01 unconfirmed", value: "8", tone: "warn" },
    ],
    policyNote:
      "This is an ordinary governed event: an agent may propose closure, but deterministic policy holds mutation authority and refuses when the safety condition is unmet. The coordinator completed its coordination; the containment proposal was refused by policy, not the agent.",
  },
  agentActivity: fleetRecall({
    coord: [OK, "Coordinate response · propose DECLARE_CONTAINED", "Coordination complete · containment proposal refused by policy"],
    recall: [OK, "Extract recall facts", "Lot LTC-4471 · O202, O203 affected"],
    net: [OK, "Reconstruct custody", "96 unique · 88 confirmed · 8 unconfirmed"],
    fulf: [OK, "Produce recovery proposal", "40 replaced · Agency 03 short 20"],
    part: [OK, "Propose partner action", "Partner pickup for O203"],
    armorPass: true,
    governanceNote: "Deterministic policy owns commit — DECLARE_CONTAINED denied · 0 mutations",
  }),
  executionEvidence: {
    title: "Recall response",
    context: "Incident INC-2231 · lot LTC-4471",
    coordinator: { name: AG_NAMES.coord, status: OK, result: "Coordination complete · containment proposal refused by policy" },
    correlationNote:
      "Specialist executions run in separately correlated Runner/session executions governed by the coordinator — application-managed correlation, not native ADK parent-child lineage.",
    specialists: [
      { name: AG_NAMES.recall, status: OK, note: "Lot LTC-4471 · O202, O203 affected" },
      { name: AG_NAMES.net, status: OK, note: "96 unique · 88 confirmed · 8 unconfirmed", toolUse: netToolUse },
      { name: AG_NAMES.fulf, status: OK, note: "40 replaced · Agency 03 short 20" },
      { name: AG_NAMES.part, status: OK, note: "Partner pickup for O203" },
    ],
    modelArmor: { pass: true },
    authority: authorityBlock({ ledgerCommitted: true }),
    refusal: {
      verdict: "DENIED · 0 MUTATIONS",
      body: "Incident Coordinator proposed DECLARE_CONTAINED. Deterministic policy denied it — 8 Site 01 cases unconfirmed. No state changed.",
    },
  },
  omittedFields: ["outcome", "tomorrow"],
};

// 11 · TODAY'S OUTCOME
P.todaysOutcome = {
  currentDay: { clock: "", operatingDate: "", dayLabel: DATE, connection: "CONNECTED", inDaybook: false },
  outcome: {
    dayLabel: "Fri · Aug 14 · end of day",
    posture: "PARTIALLY_CONTAINED",
    service: {
      fulfilledCount: 4,
      total: 5,
      fulfilledLabel: "of 5 sites recovered or fulfilled",
      fulfilledList: "Agencies 01, 02, 04, 05",
      unfulfilled: { label: "Agency 03 — unfulfilled", badge: "20-CASE SHORTFALL" },
      note: "The Agency 03 shortfall is not resolved. It remains visible and carries forward as an obligation.",
    },
    safety: {
      traced: 96,
      confirmed: 88,
      caveatTitle: '"Confirmed custody" ≠ safe, recovered, or eligible.',
      caveatBody: "88 means location/disposition is known — nothing more.",
      rows: [
        { label: "Known affected movement", badge: "BLOCKED", tone: "crit" },
        { label: "Site 01 · 8 cases", badge: "UNCONFIRMED", tone: "warn" },
      ],
    },
    nextRequirements: [
      { id: "OBL-0345", tone: "warn", badge: "OPEN", title: "Site 01 · confirm custody of 8 cases", body: "", action: { label: "Open obligation →", target: "tomorrowsDraft" } },
      { tone: "neutral", title: "Tomorrow's draft is ready", body: "Sat · Aug 15 · DRAFT_WITH_CONSTRAINTS · human approval required", action: { label: "Review tomorrow's draft →", target: "tomorrowsDraft" } },
    ],
  },
  omittedFields: ["tomorrow.detail"],
};

// 12 · TOMORROW'S DRAFT
P.tomorrowsDraft = {
  currentDay: { clock: "", operatingDate: "", dayLabel: DATE, connection: "CONNECTED", inDaybook: false, dayLabelOverride: "Sat · Aug 15 · prep" },
  tomorrow: {
    available: true,
    dayLabel: "PLAN-2026-08-15 · rev01",
    planId: "PLAN-2026-08-15",
    revision: "rev01",
    status: "DRAFT_WITH_CONSTRAINTS",
    approvalRequired: true,
    activationSupported: false,
    candidateVehicles: [
      {
        vehicleId: "TRUCK-02",
        stopCount: 2,
        candidateLoadCases: 40,
        stops: [
          { orderId: "CAND-PLAN-2026-08-15-SF-A01", agency: "Agency 01", agencyId: "AGENCY-01", cases: 18, lotId: "LTC-5090", sequence: 1, status: "CANDIDATE" },
          { orderId: "CAND-PLAN-2026-08-15-SF-A02", agency: "Agency 02", agencyId: "AGENCY-02", cases: 22, lotId: "LTC-5090", sequence: 2, status: "CANDIDATE" },
        ],
      },
    ],
    unassignedDemand: [
      { shortfallId: "SF-A03", agencyId: "AGENCY-03", cases: 20, reason: "NO_CONFIRMED_SAFE_LOT_WITH_SUFFICIENT_CASES" },
    ],
    inheritedObligations: [
      { id: "OBL-0344", badge: "RECOVERY SHORTFALL", title: "Agency 03 · 20-case shortfall recovery", origin: "↳ from Aug 14 · recall INC-2231" },
      { id: "OBL-0345", badge: "ACKNOWLEDGMENT OBLIGATION", title: "Site 01 · confirm custody of 8 cases", origin: "↳ from Aug 14 · lot LTC-4471" },
    ],
    unavailableReason: null,
  },
  omittedFields: [],
};

// HISTORY (read-only ledger)
P.history = {
  currentDay: { clock: "", operatingDate: "", dayLabel: DATE, connection: "CONNECTED", inDaybook: false, dayLabelOverride: "Fri · Aug 14 · review" },
  history: {
    asOf: "",
    ledger: [
      { time: "06:45", title: "rev07 approved by human", meta: "M. Ortega · Ops Director · KMS key version 4", tone: "ok", tag: { label: "APPROVED", tone: "ok" } },
      { time: "07:30", title: "rev07 activated", meta: "authoritative plan for the day", tone: "neutral", tag: { label: "COMMITTED", tone: "neutral" } },
      { time: "08:05", title: "O201 delivered · Agency 01", meta: "18 cases · delivery confirmation", tone: "ok", tag: { label: "COMMITTED", tone: "neutral" } },
      { time: "08:20", title: "Truck 1 refrigeration failure · INC-2210", meta: "rev08 proposed · advisory", tone: "warn", tag: { label: "ADVISORY", tone: "info" } },
      { time: "08:24", title: "rev08 approved & activated", meta: "supersedes rev07", tone: "ok", tag: { label: "APPROVED", tone: "ok" } },
      { time: "09:35", title: "Recall received · lot LTC-4471 · INC-2231", meta: "plan validity under review", tone: "crit", tag: { label: "RECALL", tone: "crit" } },
      { time: "09:36", title: "rev08 invalidated · movement barrier committed", meta: "affected: O202, O203", tone: "crit", tag: { label: "RECALL", tone: "crit" } },
      { time: "10:05", title: "Custody reconstructed · 96 unique cases", meta: "88 confirmed · 8 Site 01 unconfirmed", tone: "neutral", tag: { label: "COMMITTED", tone: "neutral" } },
      { time: "10:12", title: "DECLARE_CONTAINED denied · 0 mutations", meta: "8 unconfirmed · recorded as authoritative refusal", tone: "crit", tag: { label: "REFUSED", tone: "crit" } },
    ],
    lineage: [
      { glyph: "○", tone: "neutral", text: "rev07 · approved 06:45 → superseded 08:24" },
      { glyph: "■", tone: "crit", text: "rev08 · approved 08:24 → invalidated 09:36" },
      { glyph: "▲", tone: "warn", text: "tomorrow rev01 · draft · awaiting approval" },
    ],
    note: "Earlier operating days would list here as their own daybooks. This prototype includes only Fri Aug 14.",
  },
  omittedFields: [],
};

// =====================================================================
// Adapter
// =====================================================================
function withShell(beatId: BeatId, proj: PartialProjection): FullShelfProjection {
  const meta = BEATS.find((b) => b.id === beatId)!;
  const incidentSummary = proj.incidentSummary ?? { activeCount: 0, incidents: [] };
  const cd = proj.currentDay;
  const currentDay = {
    ...cd,
    clock: meta.time,
    operatingDate: cd.dayLabelOverride || DATE,
    dayLabel: DATE,
  };
  const asOf = meta.time === "—" ? DATE : `${meta.time} · Fri Aug 14`;
  const out: FullShelfProjection = {
    ...proj,
    beatId,
    asOf,
    dataMode: DATA_MODE,
    currentDay,
    incidentSummary,
    omittedFields: proj.omittedFields || [],
  };
  if (out.history) out.history = { ...out.history, asOf };
  return out;
}

// deep clone so consumers can't mutate the fixture
const clone = <T,>(o: T): T =>
  typeof structuredClone === "function" ? structuredClone(o) : JSON.parse(JSON.stringify(o));

export function createFixtureDataSource(opts: { latencyMs?: number } = {}): FullShelfDataSource {
  const latencyMs = opts.latencyMs ?? 140; // real async → real loading state
  return {
    getProjection(beatId: BeatId): Promise<FullShelfProjection> {
      return new Promise((resolve, reject) => {
        setTimeout(() => {
          const proj = P[beatId];
          if (!proj) {
            reject(new Error(`Unknown beat: ${beatId}`));
            return;
          }
          resolve(clone(withShell(beatId, proj)));
        }, latencyMs);
      });
    },
  };
}

export default createFixtureDataSource;
