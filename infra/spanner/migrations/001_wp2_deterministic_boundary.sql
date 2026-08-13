-- Additive WP2 schema for deterministic command idempotency and lot barriers.
-- Apply only after preflight against an isolated audit database.

ALTER TABLE Receipts ADD COLUMN idempotency_key STRING(128);
ALTER TABLE Receipts ADD COLUMN caller_subject STRING(128);
ALTER TABLE Receipts ADD COLUMN caller_email STRING(320);
ALTER TABLE Receipts ADD COLUMN agent_role STRING(64);

CREATE UNIQUE NULL_FILTERED INDEX ReceiptsByIdempotencyKey
ON Receipts(tenant_id, idempotency_key);

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
