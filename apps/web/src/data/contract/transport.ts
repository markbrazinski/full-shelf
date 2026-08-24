// =====================================================================
// Full Shelf — raw transport types for contract v2
// ---------------------------------------------------------------------
// A structural mirror of packages/contracts/schemas/ui_projection.json at
// tag full-shelf-backend-fe-contract-v2 (ac2c565). These are the wire
// shapes exactly as the orchestrator emits them: snake_case, nullable
// where the contract is nullable, absent where the contract omits.
//
// Nothing here is a view model. Absent stays absent — never defaulted to
// "" or 0 — so the normalizer can tell "not supplied" from "supplied as
// zero". See normalize.ts for the single mapping layer.
// =====================================================================

export type RawOmittedField = { field: string; reason: string };

export interface RawProjectionBoundary {
  as_of: string;
  mode: string;
  omitted_fields: RawOmittedField[];
}

export interface RawPlanRevision {
  plan_id: string;
  revision: string;
  status: string;
}

export interface RawCommitment {
  revision: string;
  order_id: string;
  agency: string | null;
  cases: number | null;
  lot_id: string | null;
  vehicle: string | null;
  status: string | null;
}

export interface RawPlanDiffEntry {
  change_type: string;
  order_id: string | null;
  cases: number | null;
  target_vehicle: string | null;
}

export interface RawApproval {
  approval_id: string;
  plan_id: string | null;
  source_revision: string | null;
  proposed_revision: string | null;
  plan_diff_hash: string | null;
  // The key VERSION only. A KMS signature is never transported.
  kms_key_version: string | null;
  verified_at: string;
  state: string;
  plan_diff: RawPlanDiffEntry[];
  approver_identity_class: string;
  approver_domain: string | null;
  authority_scope: string | null;
  expires_at: string | null;
}

export interface RawModelArmorScreening {
  result: string;
  correlation_id: string | null;
}

export interface RawRefusal {
  decision: string;
  mutations_applied: number;
  receipt_id: string;
  committed_at: string;
}

export interface RawIncident {
  incident_id: string;
  incident_type: string | null;
  status: string;
  terminal_state: string;
  affected_lot_id: string | null;
  model_armor_screening: RawModelArmorScreening | null;
  refusal: RawRefusal | null;
}

export interface RawPlanConstraint {
  plan_id: string | null;
  constraint_type: string | null;
  description: string | null;
}

export interface RawAllocation {
  allocation_id: string;
  incident_id: string | null;
  status: string | null;
  agency_id?: string | null;
  lot_id?: string | null;
  cases?: number | null;
}

export interface RawShortfall {
  shortfall_id: string;
  incident_id: string | null;
  status: string | null;
  agency_id?: string | null;
  cases?: number | null;
}

export interface RawRecoveryExplanation {
  basis: string;
  cases_requested: number;
  cases_allocated: number;
  cases_short: number;
  agencies_allocated: number;
  agencies_short: number;
  statement: string;
  // Null unless a rationale was actually persisted. Never synthesized.
  persisted_agent_rationale: string | null;
}

export interface RawRecovery {
  allocations: RawAllocation[];
  shortfalls: RawShortfall[];
  explanation: RawRecoveryExplanation | null;
}

export interface RawDispatchStop {
  order_id: string;
  agency: string | null;
  cases: number | null;
  lot_id: string | null;
  status: string | null;
  assignment_type: string;
}

export interface RawDispatchVehicle {
  vehicle_id: string;
  name: string | null;
  capacity_cases: number | null;
  assigned_cases: number | null;
  remaining_cases: number | null;
  at_capacity: boolean | null;
  is_operational: boolean | null;
  stop_count: number;
  stops: RawDispatchStop[];
}

export interface RawPartnerPickup extends RawDispatchStop {
  assigned_vehicle_id: null;
}

export interface RawDispatch {
  plan_id: string | null;
  revision: string | null;
  vehicles: RawDispatchVehicle[];
  partner_pickups: RawPartnerPickup[];
}

export interface RawCurrentDay {
  plan_id: string;
  plan_revisions: RawPlanRevision[];
  active_plan_revision: string | null;
  commitments: RawCommitment[];
  vehicles: unknown[] | null;
  approvals: RawApproval[];
  incidents: RawIncident[];
  plan_constraints: RawPlanConstraint[];
  recovery: RawRecovery;
  dispatch: RawDispatch | null;
}

export interface RawAgent {
  agent_id: string;
  display_name: string;
  role: string;
  // COMPLETED | NOT_YET_REPORTED only. A synchronous runtime cannot
  // express Running or Waiting, so the contract never emits one.
  state: string;
  run_id: string | null;
  session_id: string | null;
  model_used: string | null;
  adk_framework: string | null;
  deterministic_validation: string | null;
  declared_tools: string[];
  tool_invocations: unknown[];
}

export interface RawAgentActivity {
  manifest_version: string | null;
  root_agent_id: string | null;
  coordinator_session_id: string | null;
  coordination_run_id: string | null;
  proposal_status: string | null;
  delegation_trace: unknown[];
  committed_at: string;
  agents: RawAgent[];
  topology: string;
  governed_sequence: string[];
}

export interface RawCustodyPosition {
  node_id: string;
  name: string;
  node_type: string;
  on_hand_cases: number;
  acknowledgment_status: string;
  path_depth: number;
}

export interface RawCustodyEdge {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  case_count: number;
  lot_id: string;
  is_sub_distribution: boolean;
}

export interface RawCustodyGraph {
  classification: string;
  tenant_id: string;
  lot_id: string;
  query_engine: string;
  node_count: number;
  max_path_depth: number;
  unique_current_cases: number;
  confirmed_cases: number;
  unconfirmed_cases: number;
  intermediate_subtotals_readded: boolean;
  current_positions: RawCustodyPosition[];
  unconfirmed_positions: RawCustodyPosition[];
  edges: RawCustodyEdge[];
  paths: { root_node_id: string; destination_node_id: string; path_depth: number }[];
}

export interface RawHistoryEntry {
  receipt_id: string;
  action_id: string;
  action_type: string;
  status: string;
  mutations_applied: number | null;
  committed_at: string;
}

export interface RawExecutionEvidence {
  custody_graph: RawCustodyGraph | null;
  receipts_committed: number;
  history: RawHistoryEntry[];
}

export interface RawRecallIntakeStep {
  step: string;
  state: string;
}

export interface RawRecallIntake {
  incident_id: string;
  steps: RawRecallIntakeStep[];
}

export interface RawCarryForwardObligation {
  kind: string;
  reference_id: string;
  incident_id?: string;
  lot_id?: string;
  terminal_state?: string;
}

export interface RawNextDayDraft {
  plan_id: string;
  revision: string;
  status: string;
  approval_required: boolean;
}

export interface RawProjection {
  tenant_id: string;
  operating_day: string;
  authority_scope: string;
  verified_principal_subject: string;
  classification: string;
  replay_notice?: string;
  projection_boundary: RawProjectionBoundary;
  current_day: RawCurrentDay;
  agent_activity_as_of: RawAgentActivity | null;
  execution_evidence_as_of: RawExecutionEvidence;
  carry_forward_obligations: RawCarryForwardObligation[];
  next_day_draft?: RawNextDayDraft;
  recall_intake_as_of: RawRecallIntake | null;
}
