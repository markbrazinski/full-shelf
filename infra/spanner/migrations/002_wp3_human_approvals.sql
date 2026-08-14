-- Additive WP3 schema. Apply to an isolated audit database before canonical DDL.
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
