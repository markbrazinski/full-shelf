# Work Package 3 — human approval and KMS preflight

Recorded: 2026-08-13  
Gate: a real allowlisted human approves the complete rev07-to-rev08 diff;
the private ledger independently verifies the original Google-signed operator
token before KMS signing, persists the approval before activation, and rejects
tampering or expiry with zero activation mutations.

This is builder preflight evidence, not independent certification.

## Current implementation findings

Classification: `STRUCTURALLY_VERIFIED`

- The public dispatch route uses the judge API key and hardcodes
  `operations-director@fullshelf.org`; this is not human authentication.
- The original operator token is not forwarded to or independently verified by
  the ledger.
- `full_shelf_domain.kms` falls back to a static HMAC key when managed KMS
  signing or public-key retrieval fails.
- Approval expiration is not validated.
- Approval state is not persisted as a distinct authoritative record before
  rev08 activation.

These paths cannot be accepted and must be replaced rather than extended.

## Managed preflight

Classification: `OBSERVED_LIVE`

- Cloud KMS key version
  `projects/preflight-hackathon/locations/us-central1/keyRings/full-shelf-keyring/cryptoKeys/approval-signer/cryptoKeyVersions/1`
  is enabled with algorithm `RSA_SIGN_PKCS1_2048_SHA256` and software
  protection.
- The key has no key-level IAM bindings, and project IAM has no
  `roles/cloudkms.signerVerifier` or `roles/cloudkms.publicKeyViewer` binding.
- The only Secret Manager secret name is `full-shelf-judge-api-key`.
- Neither Cloud Run service has a web OAuth client ID, allowed operator subject,
  or allowed operator email configuration.
- Repository inspection found no Google Identity Services web-client or
  immutable operator-subject configuration.

No secret values or identity tokens were read, printed, logged, or persisted.

## Blocker

Classification: `BLOCKED_WITH_TRUTHFUL_FALLBACK`

Authority Resolution Memo section 7 requires a configured Google Identity
Services web OAuth client and a real operator allowlisted by immutable Google
`sub`. It explicitly requires escalation if GIS cannot be configured and
prohibits inventing or hardcoding an approver.

Required inputs:

1. the Full Shelf Google web OAuth client ID used as the exact operator-token
   audience;
2. the immutable Google `sub` for the canonical demo operator;
3. optionally, the operator email for display and secondary allowlist checking.

The builder must not derive `sub` from an email or treat the judge API key as
human authority.

## Operator bootstrap helper

Classification: `DESIGNED`

Google requires creation of the Google Identity Services **Web application**
client in the Google Auth Platform Clients console. The similarly named
`gcloud iam oauth-clients` command manages a different IAM OAuth facility and
must not be used as a substitute.

Create the web client in project `preflight-hackathon` with this authorized
JavaScript origin:

```text
http://127.0.0.1:8787
```

No redirect URI is needed for the local JavaScript callback. Then run:

```bash
.venv/bin/python scripts/bootstrap_wp3_operator.py \
  --client-id 'YOUR_CLIENT_ID.apps.googleusercontent.com'
```

The helper binds only to loopback, opens the Google Identity Services sign-in
page, verifies the returned token through the official Google authentication
library against the exact client ID, prints only the verified `sub` and email,
and shuts down. It never logs, prints, or persists the raw ID token.

## TODO after identity configuration

Classification: `DESIGNED`

1. Add fail-closed operator-token verification to the public orchestrator
   approval route and forward the original token without logging it.
2. Independently verify that token in the private ledger against the same exact
   audience and immutable-subject allowlist.
3. Replace hardcoded principal defaults with verified claims.
4. remove the HMAC and managed-failure fallbacks; enforce the configured KMS
   key version and expiration.
5. Add an additive approval table and ledger command that persists verified
   approval evidence before rev08 activation in one governed transaction path.
6. Grant only the ledger runtime the minimum KMS signing/verifying permissions.
7. Add altered-data tests for token failures, every envelope field, expiry,
   wrong key version, proposal-only behavior, replay, and zero-mutation denial.
8. Run isolated managed signing/verification and mutation reconciliation,
   deploy Git-bound images, and repeat deployed negative-path checks.

WP4 may not begin until this gate passes.
