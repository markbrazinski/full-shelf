# ADR 003: Cryptographic KMS Approval Envelope Binding

## Context
Converting Order O203 from a standard truck delivery to a partner pickup requires human authorization from the operations director. To prevent replay attacks, unauthorized action tampering, or stale plan application, approvals must be cryptographically bound.

## Decision
1. Human approvals produce a canonical approval envelope (`rev08`) containing:
   - Approval ID, Principal ID, Incident ID (`INC-TRUCK`)
   - Target Plan ID and Expected Plan Revision (`v1`)
   - Proposed Action (`CONVERT_TO_PARTNER_PICKUP`, Order O203, 20 cases)
   - SHA-256 Payload Hash of the exact action payload
2. Google Cloud KMS signs the SHA-256 hash of the approval envelope.
3. `apps/plan-ledger` verifies the KMS signature against the envelope and payload hash before executing the plan revision to `v2`.
4. Any alteration of the payload, target order, case count, or plan revision invalidates the cryptographic verification.

## Consequences
- Guaranteed authenticity and non-repudiation of high-stakes operational overrides.
- Idempotent execution bound to a specific plan revision.
