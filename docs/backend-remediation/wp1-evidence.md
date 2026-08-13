# Work Package 1 — identity and ledger perimeter evidence

Recorded: `2026-08-13T21:20:19Z`  
Source revision: `47633924608eef9fd2b743e647952591d40fea3c`  
Status: `DEPLOYED OBSERVED` by the builder; independent acceptance is still required.

## Implemented boundary

- Added cryptographic Google ID-token verification using `google.oauth2.id_token.verify_oauth2_token`.
- Enforced signature, Google issuer, exact string audience, expiry, verified email, immutable subject, and exact email allowlists.
- Applied the verifier as a dependency to every `/api/v1/*` ledger route.
- Rejected the signature-stripped `X-Serverless-Authorization` header as application identity; Full Shelf sends the intact token in `Authorization`.
- Made the ledger URL and audience explicit, required configuration.
- Replaced unauthenticated orchestrator-to-ledger calls with Google-signed ID tokens minted for the exact ledger audience.
- Removed `allUsers` from plan-ledger IAM.
- Changed the ledger runtime to `full-shelf-ledger-sa@preflight-hackathon.iam.gserviceaccount.com`.
- Removed `roles/owner` and `roles/spanner.databaseUser` from the orchestrator SA; retained `roles/spanner.databaseReader`.
- Replaced the invalid schema-error write probe with zero-match, syntactically valid DML that accepts only `PermissionDenied` as proof.
- Built both images with immutable source tags and OCI revision label `47633924608eef9fd2b743e647952591d40fea3c`.

Google's Cloud Run service-to-service documentation states that `Authorization` carries the signed token to the application, while `X-Serverless-Authorization` has its signature removed before the user container receives it. This behavior determined the signed-header choice.

## Commits

| Commit | Purpose |
|---|---|
| `ea462c0` | Shared verifier, protected ledger routes, authenticated ledger client, invalid-token tests |
| `833c478` | Conclusive and non-mutating Spanner write-denial probe |
| `4763392` | Git-SHA-tagged image builds and OCI revision labels |

## Local verification

Command:

```text
PYTHONPATH=packages/domain:packages/observability .venv/bin/pytest -q packages/domain/tests/test_identity.py apps/plan-ledger/tests/test_ledger_auth.py apps/orchestrator/tests/test_ledger_identity.py apps/orchestrator/tests/test_spanner_auth_probe.py
```

Observed: `28 passed`, `0 failed`, `0 skipped` in 1.07 seconds. Covered missing and malformed credentials, signature failure, wrong issuer, wrong audience, expiry, unverified email, unauthorized subject/email, exact authorized identity, fail-closed configuration, pre-route denial, every-ledger-route dependency coverage, exact audience minting, and conclusive write-denial semantics.

A separate broader safe-suite attempt reached 27 passing tests and then stalled in the legacy live-KMS test. It was interrupted after 65 seconds. It is not reported as a completed suite and does not count toward WP1 acceptance.

## Managed changes and provenance

| Resource | Before | After |
|---|---|---|
| Ledger invoker IAM | `allUsers`, orchestrator SA, audit user | orchestrator SA, audit user |
| Ledger runtime | orchestrator SA | ledger SA |
| Orchestrator project roles | Owner, Spanner databaseUser, Spanner databaseReader | Spanner databaseReader; Owner/databaseUser removed |
| Orchestrator revision | `full-shelf-orchestrator-00022-l9w` | `full-shelf-orchestrator-00023-frt` |
| Ledger revision | `full-shelf-plan-ledger-00014-q6l` | `full-shelf-plan-ledger-00016-x4j` |
| Orchestrator image | mutable `v1` | `orchestrator:wp1-47633924608e`, digest `sha256:f1c40e5ee204cd1154f9b038d6ae079b52c9c96041fb74f5292125c651d3ed17` |
| Ledger image | mutable `v1` | `plan-ledger:wp1-47633924608e`, digest `sha256:b71185ed6b4290ad27dcc84c58f006e30b298b651a621f07667fb1c12ee3f811` |

Cloud Build executions:

- Ledger: `69ba21e4-9f23-4b2d-8a30-0e24803ae04e` — `SUCCESS`
- Orchestrator: `dfe7c8b8-e6bd-47e5-b0d6-ce2031dec2f2` — `SUCCESS`

## Acceptance observations

All HTTP checks used `curl -q` so local curl configuration could not inject credentials. The first plain-curl HTTP 200 was discarded after `curl -q` proved it resulted from local curl configuration.

| Acceptance case | Observed result | Evidence class |
|---|---|---|
| Missing credential | Cloud Run HTTP 403 | `OBSERVED_LIVE` |
| Unsigned token | Cloud Run HTTP 401 | `OBSERVED_LIVE` |
| Wrong issuer | HTTP 401; exact claim branch also locally verified | `OBSERVED_LIVE` + `STRUCTURALLY_VERIFIED` |
| Wrong audience | Google-signed orchestrator token for the orchestrator audience returned HTTP 401 at ledger | `OBSERVED_LIVE` |
| Expired token | HTTP 401; exact claim branch also locally verified | `OBSERVED_LIVE` + `STRUCTURALLY_VERIFIED` |
| Unauthorized subject | Google-signed ledger-SA token returned HTTP 403 | `OBSERVED_LIVE` |
| Correct orchestrator identity | Google-signed token for subject `105774551577568412756`, exact ledger audience, returned HTTP 200 on non-mutating evidence route | `OBSERVED_LIVE` |
| Direct orchestrator DML | Deployed runtime returned `PermissionDenied` / `PERMISSION_DENIED` for syntactically valid, zero-match DML | `OBSERVED_LIVE` |

The current ledger evidence route itself still overstates `OBSERVED_LIVE`; that response field is not used as proof here and remains a WP10 repair. Only the independently observed HTTP status and managed request behavior are used.

## Exact managed commands

The commands used were:

```text
gcloud run services remove-iam-policy-binding full-shelf-plan-ledger --member=allUsers --role=roles/run.invoker ...
gcloud run services update full-shelf-plan-ledger --service-account=full-shelf-ledger-sa@... ...
gcloud projects remove-iam-policy-binding preflight-hackathon --member=serviceAccount:full-shelf-orchestrator-sa@... --role=roles/owner
gcloud projects remove-iam-policy-binding preflight-hackathon --member=serviceAccount:full-shelf-orchestrator-sa@... --role=roles/spanner.databaseUser
gcloud builds submit --config cloudbuild-ledger.yaml --substitutions=_GIT_SHA=4763392...,_IMAGE_TAG=wp1-47633924608e .
gcloud builds submit --config cloudbuild-orchestrator.yaml --substitutions=_GIT_SHA=4763392...,_IMAGE_TAG=wp1-47633924608e .
gcloud run services update <service> --image=<sha-tag> --update-env-vars=<explicit identity configuration> ...
curl -q ... <ledger evidence route>
curl -q ... <orchestrator Spanner authorization probe>
```

Short-lived ID tokens were held only in shell variables, never printed or persisted, and were unset immediately after each call.

## WP1 result

Every WP1 acceptance outcome is observed. This is a builder package result, not final backend acceptance. WP2 may begin; any later boundary regression must stop subsequent work.
