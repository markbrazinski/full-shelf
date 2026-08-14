-- Additive final-remediation binding. Existing receipts remain readable, but a
-- legacy approval receipt without a fingerprint cannot authorize a replay.
ALTER TABLE Receipts ADD COLUMN request_fingerprint STRING(64);
ALTER TABLE Approvals ADD COLUMN operating_day DATE;
ALTER TABLE Approvals ADD COLUMN authority_scope STRING(128);
