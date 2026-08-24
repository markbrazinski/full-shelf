// =====================================================================
// Full Shelf — normalized frontend view models
// ---------------------------------------------------------------------
// The ONLY contract between presentation and data. Presentation
// components consume `FullShelfProjection` and never import scenario
// constants. A live backend ships by writing a second implementation of
// `FullShelfDataSource` (see data/FullShelfDataSource.ts); no component
// changes required.
// =====================================================================

export type BeatId =
  | "healthy"
  | "truckFailure"
  | "revisionReview"
  | "dispatchSchematic"
  | "rev08Active"
  | "recallReceived"
  | "recallProcessing"
  | "custodyEstablished"
  | "governedRecovery"
  | "governanceRefusal"
  | "todaysOutcome"
  | "tomorrowsDraft"
  | "history";

export type DataMode = "SYNTHETIC_TEST" | "OBSERVED_LIVE" | "RECORDED_LIVE";

// Only these three may ever be shown for an agent. No Running / Waiting.
export type AgentDisplayStatus = "COMPLETED" | "NOT_YET_REPORTED" | "NOT_INVOLVED";

export type Connection = "CONNECTED" | "MONITORING" | "DISCONNECTED";

export type Posture = "NORMAL" | "INTERVENTION" | "RECALL";

// Tone drives presentation color only. Text/values come from the source.
export type Tone = "ok" | "plan" | "info" | "warn" | "crit" | "neutral";

export type OrderStateTone =
  | "delivered"
  | "planned"
  | "impacted" // "Impacted by INC-2210" — replaces AT RISK
  | "reassigned"
  | "partner"
  | "recall";

export type AuthorityClass =
  | "AGENT_PROPOSAL"
  | "DETERMINISTIC_POLICY"
  | "COMMITTED_LEDGER"
  | "CONFIRMED"
  | "OPEN";

export type CustodyStatus = "CONFIRMED" | "BLOCKED" | "UNCONFIRMED";

// Sentinel for historical fields that were genuinely not retained.
// Never substitute a later value in its place.
export const HISTORICAL_NOT_RETAINED = "Historical value not retained";

// --------------------------- shared shell ----------------------------

export interface StatusPill {
  label: string;
  tone: Tone;
  glyph?: string;
}

export interface Commitment {
  id: string;
  lot: string;
  lotFlagged: boolean; // lot named in an active recall
  agency: string;
  cases: number;
  vehicle: string;
  stateLabel: string; // e.g. "Impacted by INC-2210"
  stateTone: OrderStateTone;
}

export interface RecentActivityItem {
  glyphTone: Tone;
  title: string;
  meta: string;
}

export interface NeedsAttention {
  tone: Tone;
  kicker: string;
  incident: string; // trailing incident ref, may be ""
  title: string;
  body: string;
  action?: { label: string; target: BeatId };
}

export interface CapacityPanel {
  title: string;
  assignedLabel: string; // e.g. "36 / 60 assigned"
  fillPct: number; // 0–100 (schematic bar only)
  spareLabel?: string;
  note?: string;
}

export interface ApprovalRecord {
  decision: string;
  approver: string;
  role: string;
  timestamp: string;
  kmsKeyVersion: string | null; // key VERSION / verification ref — never a signature
  kmsNote: string;
  ledgerCommitted: boolean;
  ledgerNote: string;
}

export interface SidePanelText {
  kicker: string;
  tone: Tone;
  lines: string[];
}

export interface CurrentDayView {
  clock: string;
  operatingDate: string;
  dayLabel: string;
  connection: Connection;
  inDaybook: boolean; // daybook header shown (Today-surface beats)
  dayLabelOverride?: string;
  posture?: Posture;
  authRev?: string;
  authPill?: StatusPill;
  openObligations?: { count: number; note: string; tone: Tone };
  needsAttention?: NeedsAttention;
  commitmentsSummary?: { label: string; tone: Tone };
  commitments?: Commitment[];
  affectedPanel?: SidePanelText;
  capacity?: CapacityPanel;
  approvalRecord?: ApprovalRecord;
  recallNoticePanel?: SidePanelText;
  recentActivity?: RecentActivityItem[];
  obligationsNote?: string; // side "open obligations" copy, or NOT_RETAINED
}

// ------------------------- incident / recall -------------------------

export interface DiffRow {
  id: string;
  meta: string; // "Agency 02 · 22 cases · lot LTC-4471"
  before: string;
  after: string;
}

export interface IncidentView {
  ref: string;
  banner: { title: string; body: string; tone: Tone };
  posture?: string; // e.g. "PARTIALLY_CONTAINED"
  diffRows?: DiffRow[];
  rationale?: {
    observation: string;
    constraints: string;
    feasibleOption: string;
    requiredAuthority: string;
  };
  unaffectedNote?: string;
  approvalCta?: { label: string; guard: string };
}

export interface DispatchStop {
  title: string;
  sub: string;
  tone: OrderStateTone;
  // Structured contract facts. Presentation reads these directly; nothing
  // parses them back out of `title`/`sub`, which are display strings.
  orderId: string;
  agency: string | null;
  cases: number | null;
  lotId: string | null;
  /** 1-based committed manifest position; null for a partner pickup. */
  sequence: number | null;
  vehicleId: string | null;
}
export interface DispatchVehicle {
  label: string;
  status: string;
  tone: OrderStateTone;
}

export interface DispatchView {
  title: string;
  schematicLabel: string; // "Dispatch schematic · not live GPS"
  note: string;
  // node text only — geometry is presentational and lives in the component
  stops: Record<string, DispatchStop>;
  vehicles: Record<string, DispatchVehicle>;
  capacityDecision: {
    beforeLabel: string;
    beforeValue: string;
    addLabel: string;
    addValue: string;
    afterLabel: string;
    afterValue: string;
    afterFillPct: number;
    remainingLabel: string;
    remainingValue: string;
    needsLabel: string;
    needsValue: string;
    verdict: string;
    explain: string;
  };
}

export interface IntakeStep {
  key: string;
  title: string;
  body: string;
  status: "COMPLETE" | "IN_PROGRESS" | "PENDING";
}

export interface RecallView {
  ref: string;
  banner: { title: string; body: string };
  intake: IntakeStep[];
  sourceExcerpt: string;
  sourceAnchoredLot: string;
  affectedCommitments: string;
  modelArmor: "PASS" | null; // PASS only AFTER screening completes
  invalidation?: { title: string; body: string };
}

// --------------------------- agent activity --------------------------

export interface AgentCell {
  key: string;
  name: string;
  isCoordinator: boolean;
  status: AgentDisplayStatus;
  task: string;
  result: string | null; // null when NOT_YET_REPORTED / NOT_INVOLVED
}

export interface BoundaryChip {
  label: string;
  detail: string;
  pass: boolean;
}

export interface AgentActivityView {
  adkLabel: string; // "ADK 2.6.1"
  note: string;
  agents: AgentCell[];
  boundaries: BoundaryChip[]; // Model Armor etc. — visually NOT an agent
  governanceNote?: string; // policy refusal note (never an agent status)
}

// ------------------------------ custody ------------------------------

export interface CustodyNode {
  key: string;
  label: string;
  value: number;
  status: CustodyStatus;
  note?: string;
}

export interface CustodyView {
  question: string;
  totalUnique: number;
  nodes: CustodyNode[];
  reconciliation: { label: string; value: string; tone: Tone; muted?: boolean }[];
  sumExpression: string;
  caveat: string; // "Confirmed custody ≠ safe, recovered, or eligible."
}

// ----------------------------- recovery ------------------------------

export interface RecoveryItem {
  text: string;
  tone: Tone;
  authorityClass: AuthorityClass;
}

export interface RecoveryView {
  question: string;
  items: RecoveryItem[];
  safeReplacements: { total: number; breakdown: string };
  shortfall: { value: number; agency: string; note: string };
  authorityNote: string;
}

// ---------------------------- governance -----------------------------

export interface GovernanceView {
  question: string;
  proposal: { label: string; time: string; text: string };
  policyEvalLabel: string;
  refusal: {
    verdict: string; // "DENIED · 0 MUTATIONS"
    body: string;
    reason: string;
    mutations: string; // "0"
    recordedAt: string;
    posture: string; // "PARTIALLY_CONTAINED"
  };
  whyCannotClose: { label: string; value: string; tone: Tone }[];
  policyNote: string;
}

// ------------------------ outcome / tomorrow -------------------------

export interface OutcomeView {
  dayLabel: string;
  posture: string;
  service: {
    fulfilledCount: number;
    total: number;
    fulfilledLabel: string;
    fulfilledList: string;
    unfulfilled: { label: string; badge: string };
    note: string;
  };
  safety: {
    traced: number;
    confirmed: number;
    caveatTitle: string;
    caveatBody: string;
    rows: { label: string; badge: string; tone: Tone }[];
  };
  nextRequirements: {
    id?: string;
    tone: Tone;
    badge?: string;
    title: string;
    body: string;
    action: { label: string; target: BeatId };
  }[];
}

export interface CandidateStop {
  orderId: string;
  agency: string | null;
  agencyId: string | null;
  cases: number | null;
  lotId: string | null;
  sequence: number;
  /** Always "CANDIDATE" — never an activatable state. */
  status: string;
}

export interface CandidateVehicle {
  vehicleId: string | null;
  stops: CandidateStop[];
  stopCount: number;
  candidateLoadCases: number;
}

export interface UnassignedDemand {
  shortfallId: string;
  agencyId: string | null;
  cases: number | null;
  reason: string | null;
}

/**
 * Saturday's candidate schedule.
 *
 * `available: false` is a first-class state, not an error and not a reason to
 * substitute a fallback. When the contract returns no candidate plan the UI
 * renders an explicit unavailable panel: no routes, markers, manifests,
 * assignments, loads, lots, or feasibility claims.
 */
export interface TomorrowView {
  available: boolean;
  dayLabel: string;
  planId: string | null;
  revision: string | null;
  status: string | null; // "DRAFT_WITH_CONSTRAINTS"
  approvalRequired: boolean;
  /** Always false. No activation path exists for a draft. */
  activationSupported: boolean;
  candidateVehicles: CandidateVehicle[];
  unassignedDemand: UnassignedDemand[];
  /** Safety and continuity carry-forwards inherited by the draft. */
  inheritedObligations: { id: string; badge: string; title: string; origin: string }[];
  /** Why the candidate plan is unavailable, when it is. */
  unavailableReason: string | null;
}

// -------------------------- execution record -------------------------

export interface SpecialistEvidence {
  name: string;
  status: AgentDisplayStatus;
  note: string;
  // ONLY Network & Custody may carry tool-use evidence.
  toolUse?: { label: string; evidence: string };
}

export interface ExecutionEvidenceView {
  title: string;
  context: string;
  coordinator: { name: string; status: AgentDisplayStatus; result: string | null };
  correlationNote: string; // application-managed correlation, NOT parent-child
  specialists: SpecialistEvidence[];
  modelArmor: { pass: boolean } | null;
  authority: {
    policyText: string;
    ledgerCommitted: boolean;
    ledgerReceiptRef: string | null; // null → "bound in backend"; never invented
    kmsKeyVersion: string | null; // version / verification ref; never a signature
    note: string;
  };
  refusal?: { verdict: string; body: string };
}

// ------------------------------ history ------------------------------

export interface HistoryView {
  asOf: string;
  ledger: { time: string; title: string; meta: string; tone: Tone; tag: StatusPill }[];
  lineage: { text: string; tone: Tone; glyph: string }[];
  note: string;
}

// --------------------------- the projection --------------------------

/**
 * Incidents live at this boundary, derived from `current_day.incidents`.
 *
 * The nav badge reads `activeCount`. It is NEVER inferred from which view is
 * open or from demo state: an incident is active when the contract says it is
 * open at this boundary, and resolved when the contract says it resolved.
 */
export interface IncidentSummary {
  activeCount: number;
  incidents: {
    id: string;
    type: string | null;
    status: string;
    terminalState: string;
    affectedLotId: string | null;
    /** True while the incident is not in a resolved/terminal state. */
    active: boolean;
  }[];
}

/**
 * A pending repair proposal: what the agents propose, not what anyone
 * authorized. Present only while the plan it repairs is still active.
 *
 * `activationSupported` is always false. Approving runs the existing
 * verified-human -> KMS -> ledger path; this object never activates anything.
 */
export interface RepairProposalView {
  proposalId: string;
  sourceEventId: string | null;
  planId: string | null;
  /** Raw revision ids stay for evidence surfaces; primary UI says "Active plan". */
  sourceRevision: string | null;
  proposedRevision: string | null;
  failedVehicleId: string | null;
  rerouteOrderId: string;
  rerouteCases: number;
  rerouteTargetVehicle: string;
  pickupOrderId: string;
  pickupCases: number;
  planDiffHash: string | null;
  absorbing: {
    vehicleId: string | null;
    capacityCases: number | null;
    committedCases: number | null;
    projectedCases: number | null;
  };
  authority: string;
  approvalRequired: boolean;
  activationSupported: boolean;
}

export interface RecallSourceView {
  channel: string;
  noticeFormat: string;
  receivedAt: string;
  /** Always false. Full Shelf does not poll or monitor the FDA. */
  monitoringClaimed: boolean;
  classification: string;
}

export interface FullShelfProjection {
  beatId: BeatId;
  asOf: string;
  dataMode: DataMode;
  incidentSummary: IncidentSummary;
  repairProposal?: RepairProposalView;
  recallSource?: RecallSourceView;
  currentDay: CurrentDayView;
  incident?: IncidentView;
  recall?: RecallView;
  dispatch?: DispatchView;
  agentActivity?: AgentActivityView;
  custody?: CustodyView;
  recovery?: RecoveryView;
  governance?: GovernanceView;
  outcome?: OutcomeView;
  tomorrow?: TomorrowView;
  executionEvidence?: ExecutionEvidenceView;
  history?: HistoryView;
  omittedFields: string[]; // surfaces "field not yet available" honestly
}

export interface BeatMeta {
  id: BeatId;
  time: string;
  label: string;
}
