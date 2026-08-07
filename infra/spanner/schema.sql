-- Spanner Relational Schema for Full Shelf

CREATE TABLE Tenants (
  tenant_id STRING(64) NOT NULL,
  name STRING(256) NOT NULL,
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id);

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

CREATE TABLE Incidents (
  tenant_id STRING(64) NOT NULL,
  incident_id STRING(64) NOT NULL,
  parent_coordinator_id STRING(64) NOT NULL,
  incident_type STRING(64) NOT NULL,
  status STRING(64) NOT NULL,
  affected_lot_id STRING(64),
  created_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
  resolved_at TIMESTAMP
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
  timestamp TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, receipt_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE TABLE CustodyNodes (
  tenant_id STRING(64) NOT NULL,
  node_id STRING(64) NOT NULL,
  node_type STRING(32) NOT NULL,
  name STRING(128) NOT NULL,
  on_hand_cases INT64 NOT NULL
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
      KEY (node_id)
      LABEL Node
      PROPERTIES (node_id, node_type, name, on_hand_cases)
  )
  EDGE TABLES (
    CustodyEdges
      KEY (edge_id)
      SOURCE KEY (source_node_id) REFERENCES CustodyNodes (node_id)
      DESTINATION KEY (target_node_id) REFERENCES CustodyNodes (node_id)
      LABEL TRANSFERRED_TO
      PROPERTIES (edge_id, lot_id, case_count, is_sub_distribution)
  );
