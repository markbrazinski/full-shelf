export interface TruckSummary {
  vehicle_id: string;
  name: string;
  capacity: number;
  assigned_cases: number;
}

export interface DeliveryOrder {
  order_id: string;
  agency: string;
  cases: number;
  lot_id: string;
  vehicle: string;
}

export interface PlanPreviewResponse {
  tenant_id: string;
  date: string;
  active_plan_revision: string;
  trucks: TruckSummary[];
  deliveries: DeliveryOrder[];
  status: string;
}

export interface ApprovalEnvelope {
  approval_id: string;
  tenant_id: string;
  operating_day: string;
  authority_scope: string;
  rev_id: string;
  principal_id: string;
  incident_id: string;
  plan_id: string;
  source_revision: string;
  proposed_revision: string;
  plan_diff: {
    source_revision: string;
    proposed_revision: string;
    reroute_order_id: string;
    reroute_cases: number;
    reroute_target_vehicle: string;
    pickup_order_id: string;
    pickup_cases: number;
    plan_diff_hash: string;
  };
  kms_key_version: string;
  kms_signature: string;
  expires_at: string;
}

export interface ExecuteActionRequest {
  action_id: string;
  tenant_id: string;
  agent_role: string;
  action_type: string;
  plan_id: string;
  expected_revision: string;
  parameters: Record<string, unknown>;
  approval_envelope?: ApprovalEnvelope;
  idempotency_key: string;
}

export interface ActionReceipt {
  receipt_id: string;
  action_id: string;
  tenant_id: string;
  plan_revision_id: string;
  action_type: string;
  status: 'SUCCESS' | 'DENIED' | 'REJECTED';
  timestamp: string;
  mutations_applied: number;
  message: string;
  trace_id: string;
}

export interface RecallResponse {
  status: string;
  lot_id: string;
  hazard: string;
  plan_status: string;
  reconciliation: {
    total_unique_physical_cases: number;
    node_breakdown: Record<string, number>;
    sub_distributed_unconfirmed_cases: number;
    terminal_status: string;
  };
  service_impact: {
    safely_supplied_agencies: string[];
    shortfall_agency: string;
    shortfall_cases: number;
  };
}

export interface SystemEvidence {
  gcp_project_id: string;
  region: string;
  spanner_database: string;
  kms_key_name: string;
  active_plan_revision: string;
  recalled_lots: string[];
  total_receipts_recorded: number;
}
