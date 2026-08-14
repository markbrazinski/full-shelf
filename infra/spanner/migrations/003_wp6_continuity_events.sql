-- Additive WP6 schema. Apply to an isolated audit database before canonical DDL.
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
