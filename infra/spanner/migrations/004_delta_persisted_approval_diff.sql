-- Persist the KMS-bound repair diff so activation can independently read the
-- committed approval in a later transaction. Existing rows, if any, remain
-- readable; all approvals written by this candidate populate the column.
ALTER TABLE Approvals ADD COLUMN plan_diff_json STRING(MAX);
