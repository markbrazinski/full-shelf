# Work Package 3 — human approval and KMS evidence

Recorded: 2026-08-13  
Implementation commit: `3de6e361a1ec49fd85c73b987b2b34522b0387b4`

This is builder evidence, not independent certification.

## Identity and structural boundary

Classification: `STRUCTURALLY_VERIFIED`

- Google Identity Services produced a real operator ID token for OAuth client
  `620464070103-ablut31si4neq0r8ibdc7hhtla1klls2.apps.googleusercontent.com`.
  The loopback verifier cryptographically validated it and observed immutable
  subject `108080450585792522893` and display email
  `markbrazinski@gmail.com`. The raw token was not logged or retained.
- Both the public orchestrator approval route and private ledger approval route
  verify signature, issuer, expiry, exact OAuth audience, immutable subject,
  and verified email. The original operator token is forwarded only in memory
  and the ledger verifies it independently.
- The generic command route refuses `APPROVE_REPAIR_PLAN`; the former action
  route returns HTTP 410. Unsigned `APPLY_REPAIR_PLAN` fails before mutation.
- The ledger constructs the signed canonical action set and derives repaired
  orders from immutable source-revision rows. A request cannot append unrelated
  order mutations to a valid signature.
- HMAC and KMS-failure fallbacks were removed. KMS error, malformed signature,
  expiry, wrong key version, changed plan/revision/action/quantity/principal/
  incident/hash, and verification failure all fail closed.
- The approval record, source-plan supersession, rev08 insertion, derived order
  insertion, and receipt share one deterministic ledger transaction.

## Local verification

Classification: `MEASURED`

- 88 safe tests collected and 88 passed.
- Python compilation and `git diff --check` passed.
- Tests cover independent human-token gating before KMS, proposal-only behavior,
  unsigned activation denial, source-derived mutation, every bound-field
  tamper, expiry, wrong key version, stable duplicate semantics, and managed
  KMS failure without fallback.
- The obsolete shared-canonical mutation test and token-printing deployed
  script were removed.

## Isolated managed replay

Classification: `OBSERVED_LIVE`

Database: `full-shelf-audit-wp2-20260813`  
Tenant: `wp3-audit-tenant-20260813-v1`

The verifier refuses canonical or non-audit database names. It used the live
Cloud KMS key and an altered `rev42` to `rev43` scenario:

```json
{"active_repaired_revision_count":1,"approval_count":1,"database":"full-shelf-audit-wp2-20260813","duplicate_additional_mutations":0,"duplicate_receipt":"RCT-B8FEA40EE527953677D4E758","expiry_rejected":true,"first_receipt":"RCT-B8FEA40EE527953677D4E758","kms_key_version":"projects/preflight-hackathon/locations/us-central1/keyRings/full-shelf-keyring/cryptoKeys/approval-signer/cryptoKeyVersions/1","partner_pickup_count":1,"receipt_count":1,"rerouted_order_count":1,"tamper_rejected":true,"tenant":"wp3-audit-tenant-20260813-v1"}
```

The local Spanner client again emitted a non-fatal Cloud Monitoring resource
label warning after authoritative readback completed.

## Canonical schema and KMS IAM

Classification: `OBSERVED_LIVE`

- Additive migration `002_wp3_human_approvals.sql` was proven in the audit
  database and then applied to `full-shelf-main`.
- Canonical counts before and after deployed negative tests remained exactly
  three plan revisions, three receipts, and zero approvals.
- Only `full-shelf-ledger-sa` has `roles/cloudkms.signerVerifier`, scoped to the
  single `approval-signer` key. No project-wide KMS role was added.
- Impersonating that ledger runtime, Cloud KMS signed `AGENTS.md` with key
  version 1 and OpenSSL verification against the managed public key returned
  `Verified OK`.

## Build and deployment

Classification: `OBSERVED_LIVE`

| Service | Build | Digest | Ready revision |
|---|---|---|---|
| orchestrator | `d7950f96-658f-46c1-8962-800a9010081a` | `sha256:416d73940105156a9ee9ab1f8189e5e97b075e847d366a0d40ee52d677fca8c9` | `full-shelf-orchestrator-00025-lhf` |
| plan-ledger | `eaef4fc5-dac3-41e0-b084-f4b2c3c0407b` | `sha256:124f8e2c41b08987c9a682b13f42e2ce3a26ae92de4e81bd96d42350ceea649f` | `full-shelf-plan-ledger-00018-vpg` |

Both builds report the full implementation Git SHA and both revisions serve
100 percent traffic under the intended service accounts. The private ledger
still has no `allUsers` invoker.

Using a valid orchestrator workload token against the deployed ledger:

- missing original human token returned 401
  `OPERATOR_GOOGLE_ID_TOKEN_REQUIRED`;
- generic approval-command bypass returned 403 `USE_HUMAN_APPROVAL_ROUTE`;
- legacy activation returned 410
  `USE_AUTHENTICATED_HUMAN_APPROVAL_ROUTE`;
- direct Spanner reconciliation remained `plans=3, receipts=3, approvals=0`.

## Package result and limitation

Classification: `OBSERVED_LIVE`

All WP3 acceptance properties are observed across real Google operator
authentication, local altered-data tests, managed isolated KMS/Spanner replay,
ledger-runtime KMS impersonation, deployed fail-closed requests, and direct
canonical reconciliation. WP4 may begin.

Classification: `NOT_PROVEN`

A successful approval was not sent through the deployed canonical service,
because remediation tests may not activate or otherwise mutate shared
canonical plan state. Final acceptance still requires a governed end-to-end
replay and a different independent auditor.
