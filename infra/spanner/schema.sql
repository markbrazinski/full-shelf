-- Spanner Relational Schema for Full Shelf

CREATE TABLE Tenants (
  tenant_id STRING(64) NOT NULL,
  name STRING(256) NOT NULL,
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id);

CREATE TABLE Coordinators (
  tenant_id STRING(64) NOT NULL,
  coordinator_id STRING(64) NOT NULL,
  state STRING(64) NOT NULL,
  checkpoint STRING(64) NOT NULL,
  active_plan_revision STRING(32) NOT NULL,
  child_incidents STRING(MAX),
  updated_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, coordinator_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE TABLE Lots (
  lot_id STRING(64) NOT NULL,
  tenant_id STRING(64) NOT NULL,
  code STRING(64) NOT NULL,
  produce_type STRING(128) NOT NULL,
  hazard_status STRING(32) NOT NULL,
  total_cases INT64 NOT NULL,
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, lot_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE TABLE Vehicles (
  vehicle_id STRING(64) NOT NULL,
  tenant_id STRING(64) NOT NULL,
  name STRING(128) NOT NULL,
  max_capacity_cases INT64 NOT NULL,
  current_load_cases INT64 NOT NULL,
  is_operational BOOL NOT NULL
) PRIMARY KEY (tenant_id, vehicle_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE TABLE PlanRevisions (
  tenant_id STRING(64) NOT NULL,
  plan_id STRING(64) NOT NULL,
  revision STRING(32) NOT NULL,
  status STRING(32) NOT NULL,
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, plan_id, revision),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE TABLE Orders (
  tenant_id STRING(64) NOT NULL,
  plan_id STRING(64) NOT NULL,
  revision STRING(32) NOT NULL,
  order_id STRING(64) NOT NULL,
  destination_agency_id STRING(64) NOT NULL,
  destination_agency_name STRING(128) NOT NULL,
  cases INT64 NOT NULL,
  lot_id STRING(64) NOT NULL,
  assigned_vehicle_id STRING(64),
  status STRING(32) NOT NULL
) PRIMARY KEY (tenant_id, plan_id, revision, order_id),
  INTERLEAVE IN PARENT PlanRevisions ON DELETE CASCADE;

CREATE TABLE PlanConstraints (
  tenant_id STRING(64) NOT NULL,
  plan_id STRING(64) NOT NULL,
  revision STRING(32) NOT NULL,
  constraint_type STRING(64) NOT NULL,
  subject_id STRING(64) NOT NULL,
  details STRING(MAX) NOT NULL,
  priority INT64 NOT NULL,
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, plan_id, revision, constraint_type, subject_id),
  INTERLEAVE IN PARENT PlanRevisions ON DELETE CASCADE;

CREATE TABLE InboundEvents (
  tenant_id STRING(64) NOT NULL,
  source_event_id STRING(256) NOT NULL,
  event_type STRING(64) NOT NULL,
  status STRING(32) NOT NULL,
  payload STRING(MAX) NOT NULL,
  occurred_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, source_event_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE TABLE Incidents (
  tenant_id STRING(64) NOT NULL,
  incident_id STRING(64) NOT NULL,
  parent_coordinator_id STRING(64) NOT NULL,
  incident_type STRING(64) NOT NULL,
  status STRING(64) NOT NULL,
  affected_lot_id STRING(64),
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
  resolved_at TIMESTAMP,
  details STRING(MAX),
  terminal_state STRING(64)
) PRIMARY KEY (tenant_id, incident_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE TABLE Receipts (
  tenant_id STRING(64) NOT NULL,
  receipt_id STRING(64) NOT NULL,
  action_id STRING(64) NOT NULL,
  plan_revision_id STRING(32) NOT NULL,
  action_type STRING(64) NOT NULL,
  status STRING(32) NOT NULL,
  mutations_applied INT64 NOT NULL,
  message STRING(MAX) NOT NULL,
  trace_id STRING(128) NOT NULL,
  idempotency_key STRING(128),
  caller_subject STRING(128),
  caller_email STRING(320),
  agent_role STRING(64),
  timestamp TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, receipt_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE UNIQUE NULL_FILTERED INDEX ReceiptsByIdempotencyKey
ON Receipts(tenant_id, idempotency_key);

CREATE TABLE Approvals (
  tenant_id STRING(64) NOT NULL,
  approval_id STRING(64) NOT NULL,
  incident_id STRING(64) NOT NULL,
  plan_id STRING(64) NOT NULL,
  source_revision STRING(32) NOT NULL,
  proposed_revision STRING(32) NOT NULL,
  approver_subject STRING(128) NOT NULL,
  approver_email STRING(320) NOT NULL,
  oauth_audience STRING(256) NOT NULL,
  plan_diff_hash STRING(64) NOT NULL,
  plan_diff_json STRING(MAX) NOT NULL,
  kms_key_version STRING(512) NOT NULL,
  kms_signature STRING(MAX) NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  verified_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
  trace_id STRING(128) NOT NULL
) PRIMARY KEY (tenant_id, approval_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE TABLE MovementBarriers (
  tenant_id STRING(64) NOT NULL,
  barrier_id STRING(64) NOT NULL,
  incident_id STRING(64) NOT NULL,
  lot_id STRING(64) NOT NULL,
  status STRING(32) NOT NULL,
  reason STRING(MAX) NOT NULL,
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
  released_at TIMESTAMP
) PRIMARY KEY (tenant_id, barrier_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE INDEX ActiveMovementBarriersByLot
ON MovementBarriers(tenant_id, lot_id, status);

CREATE TABLE RecoveryAllocations (
  tenant_id STRING(64) NOT NULL,
  allocation_id STRING(64) NOT NULL,
  incident_id STRING(64) NOT NULL,
  agency_id STRING(64) NOT NULL,
  lot_id STRING(64) NOT NULL,
  cases INT64 NOT NULL,
  status STRING(32) NOT NULL,
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, allocation_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE INDEX RecoveryAllocationsByIncident
ON RecoveryAllocations(tenant_id, incident_id, status);

CREATE TABLE RecoveryShortfalls (
  tenant_id STRING(64) NOT NULL,
  shortfall_id STRING(64) NOT NULL,
  incident_id STRING(64) NOT NULL,
  agency_id STRING(64) NOT NULL,
  cases INT64 NOT NULL,
  status STRING(32) NOT NULL,
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, shortfall_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE INDEX RecoveryShortfallsByIncident
ON RecoveryShortfalls(tenant_id, incident_id, status);

CREATE TABLE WorkItems (
  tenant_id STRING(64) NOT NULL,
  work_item_id STRING(64) NOT NULL,
  incident_id STRING(64) NOT NULL,
  work_type STRING(64) NOT NULL,
  status STRING(32) NOT NULL,
  details STRING(MAX),
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
  completed_at TIMESTAMP
) PRIMARY KEY (tenant_id, work_item_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE INDEX WorkItemsByIncident
ON WorkItems(tenant_id, incident_id, status);

CREATE TABLE CustodyNodes (
  tenant_id STRING(64) NOT NULL,
  node_id STRING(64) NOT NULL,
  node_type STRING(32) NOT NULL,
  name STRING(128) NOT NULL,
  on_hand_cases INT64 NOT NULL,
  acknowledgment_status STRING(32) NOT NULL
) PRIMARY KEY (tenant_id, node_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE TABLE CustodyEdges (
  tenant_id STRING(64) NOT NULL,
  edge_id STRING(64) NOT NULL,
  source_node_id STRING(64) NOT NULL,
  target_node_id STRING(64) NOT NULL,
  lot_id STRING(64) NOT NULL,
  case_count INT64 NOT NULL,
  is_sub_distribution BOOL NOT NULL
) PRIMARY KEY (tenant_id, edge_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

-- Spanner Graph Definition
CREATE OR REPLACE PROPERTY GRAPH CustodyGraph
  NODE TABLES (
    CustodyNodes
      KEY (tenant_id, node_id)
      LABEL Node
      PROPERTIES (tenant_id, node_id, node_type, name, on_hand_cases, acknowledgment_status)
  )
  EDGE TABLES (
    CustodyEdges
      KEY (tenant_id, edge_id)
      SOURCE KEY (tenant_id, source_node_id) REFERENCES CustodyNodes (tenant_id, node_id)
      DESTINATION KEY (tenant_id, target_node_id) REFERENCES CustodyNodes (tenant_id, node_id)
      LABEL TRANSFERRED_TO
      PROPERTIES (tenant_id, edge_id, lot_id, case_count, is_sub_distribution)
  );
