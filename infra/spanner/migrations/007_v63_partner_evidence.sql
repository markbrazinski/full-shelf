-- V6.3 additive partner custody evidence boundary.
ALTER TABLE Receipts ADD COLUMN evidence_mutations_applied INT64;

ALTER TABLE WorkItems ALTER COLUMN completed_at
  SET OPTIONS (allow_commit_timestamp=true);

CREATE TABLE PartnerEvidenceEvents (
  tenant_id STRING(64) NOT NULL,
  source_event_id STRING(256) NOT NULL,
  event_type STRING(64) NOT NULL,
  operating_day DATE NOT NULL,
  incident_id STRING(64) NOT NULL,
  partner_id STRING(64) NOT NULL,
  source_occurred_at TIMESTAMP NOT NULL,
  received_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
  source_text STRING(MAX) NOT NULL,
  source_sha256 STRING(64) NOT NULL,
  callback_subject STRING(128) NOT NULL,
  callback_email STRING(320) NOT NULL,
  callback_audience STRING(512) NOT NULL,
  callback_issuer STRING(256) NOT NULL,
  callback_provenance STRING(64) NOT NULL,
  model_armor_json STRING(MAX) NOT NULL,
  proposal_json STRING(MAX),
  proposal_sha256 STRING(64),
  policy_decision STRING(32) NOT NULL,
  policy_reasons_json STRING(MAX) NOT NULL,
  claim_verification_json STRING(MAX) NOT NULL,
  requested_mutation_json STRING(MAX),
  agent_id STRING(64),
  model_id STRING(128),
  adk_framework STRING(64),
  adk_session_id STRING(128),
  adk_invocation_id STRING(128),
  adk_event_id STRING(128),
  receipt_id STRING(64) NOT NULL,
  domain_mutations_applied INT64 NOT NULL,
  evidence_mutations_applied INT64 NOT NULL,
  committed_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (tenant_id, source_event_id),
  INTERLEAVE IN PARENT Tenants ON DELETE CASCADE;

CREATE INDEX PartnerEvidenceEventsByIncidentBoundary
ON PartnerEvidenceEvents(tenant_id, operating_day, incident_id, committed_at);
