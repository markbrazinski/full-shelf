# WP12 — Deployment and builder handoff

Recorded: `2026-08-14T03:42:18Z`  
Branch: `repair/backend-acceptance-20260813`  
Deployment source: `454bfeffa11722315cdaa015d0e5e6dfb656c9bb`  
Acceptance authority: none. Every conclusion below is builder testimony pending
fresh independent reproduction.

## Final builder result

WP1–WP11 gates were recorded before either WP12 image build began. Both services
were built from the same clean committed tree, pushed to Artifact Registry, and
deployed by immutable digest. The final orchestrator revision then replayed a
canonical and an altered notice through managed Model Armor and Gemini 3.5 via
Google ADK, and replayed canonical and altered custody topologies through managed
Spanner Graph. These safe replay endpoints made no ledger mutation; the canonical
receipt count remained 17.

This record does not declare `PASS`.

## Branch and commits by package

| Package | Implementation commits | Separate evidence / record commits |
|---|---|---|
| WP0 | — | `90dcb4a` |
| WP0.5 | — | `3994a87` |
| WP1 | `ea462c0`, `833c478`, `4763392` | `fe581db` |
| WP2 | `22d86f9` | `19429c6` |
| WP3 | `7f3359f`, `3de6e36` | `df60b80` (blocked preflight), `d155b4f` (final record) |
| WP4 | `483ee89` | `a37a275` |
| WP5 | `d65d1cf`, `e968bf4`, `61d4a18` | `47f979c` |
| WP6–WP7 | `d199c68`, `c05311c`, `68ff68e`, `aa7e2e2`, `8c2e3c5`, `619684d` | `f56ee22` |
| WP8 | `05c2ec6` | `ccd3741` |
| WP9 | `1a3ace8` | `04e8285` |
| WP10 | `a20d9dc`, `65f247d` | `32c7d8e` |
| WP11 | `a9ac78f` | `454bfef` |
| WP12 | Deployment source `454bfef`; no runtime-code delta | This handoff is committed separately after managed evidence capture |

Baseline: `bfd1e1040824da379d69add8755682bc8eafebd6`.

## Automated tests and authoritative-state safety

Exact WP11 suite result, immediately before WP12 build:

```text
133 collected
133 passed
0 failed
0 skipped
15 warnings
```

The runner forced `SPANNER_DATABASE_ID` to
`full-shelf-audit-wp6-20260813` and refused `full-shelf-main`. Direct read-only
canonical receipt counts were 17 before the suite, 17 after the suite, and 17
after all final WP12 safe replays.

## Builds, immutable images, and final revisions

| Service | Cloud Build | Build status | Image digest | Final revision | Traffic |
|---|---|---|---|---|---:|
| orchestrator | `0aaa79bb-87a0-4253-9334-c46472f204bc` | SUCCESS | `sha256:f2dd5e6d76b18b6b31601c2efae1b28892fd7d10059b888d5da64fcc10253e58` | `full-shelf-orchestrator-00042-xhj` | 100% |
| plan-ledger | `f3366439-f107-4051-915d-4d944a652479` | SUCCESS | `sha256:62a51e73bec6ac58dcbeecbede637513f49add3773b5f10b00f703fd68fdc11e` | `full-shelf-plan-ledger-00022-rv2` | 100% |

Both Cloud Build substitution records contain exact `_GIT_SHA`
`454bfeffa11722315cdaa015d0e5e6dfb656c9bb`. Both image builds applied that
value as `org.opencontainers.image.revision`. Cloud Run template labels and the
non-secret `FULL_SHELF_SOURCE_REVISION` values match it, and the
`FULL_SHELF_IMAGE_DIGEST` values match the deployed immutable images.

The initial immutable-image revisions (`orchestrator-00041-twl` and
`plan-ledger-00021-nm8`) exposed stale WP10 values in those two provenance
environment variables. The evidence endpoint detected the mismatch. The values
were corrected without changing either image, producing the final revisions
above; all canonical and altered replays were repeated on the final orchestrator
revision.

## Final managed replay observations

| Path | Trace ID | Managed readback | Result |
|---|---|---|---|
| Canonical Spanner Graph | `aaaabbbbccccddddeeeeffff00001111` | 4 Cloud Trace spans, including `CloudSpanner.Snapshot.execute_sql` | LTC-4471; 96 unique cases; depth 2; 6 nodes; no subtotal re-addition |
| Altered Spanner Graph | `bbbbccccddddeeeeffff000011112222` | 4 Cloud Trace spans, including `CloudSpanner.Snapshot.execute_sql` | ALT-LOT-9001; 51 unique cases; depth 4; 8 nodes; audit DB only |
| Canonical Model Armor → ADK | `ccccddddeeeeffff0000111122223333` | 6 spans, including ADK invocation, `call_llm`, and `generate_content gemini-3.5-flash` | Managed allow; source-anchored LTC-4471 extraction; policy-review ready; zero ledger attempts |
| Altered Model Armor → ADK | `ddddeeeeffff00001111222233334444` | 6 spans, including ADK invocation, `call_llm`, and `generate_content gemini-3.5-flash` | Managed allow; source-anchored ALT-8842 extraction; policy-review ready; zero ledger attempts |
| Final system evidence | `eeeeffff000011112222333344445555` | 8 spans: server execution plus six Spanner reads | Revision `00042-xhj`, exact source/digest, graph 96/depth 2, no failed checks |

Sanitized Model Armor operation records for the two final notice replays:

| Scenario | Managed insert ID | Template / region | Operation | Result |
|---|---|---|---|---|
| Canonical | `fa3f350d-8c9d-46c8-a6ba-60aa476b7b79` | `full-shelf-recall-input-v1` / `us-central1` | `SANITIZE_USER_PROMPT` | invocation success; four filters executed successfully; no match; allow |
| Altered | `2f8c08d9-32e8-4f6b-8e38-f56cc64b434d` | `full-shelf-recall-input-v1` / `us-central1` | `SANITIZE_USER_PROMPT` | invocation success; four filters executed successfully; no match; allow |

Raw prompt content and credentials are intentionally absent from this evidence.

## IAM delta and final perimeter

WP12 changed no IAM binding. Final project roles observed:

```text
full-shelf-orchestrator-sa:
  roles/aiplatform.user
  roles/cloudtasks.enqueuer
  roles/cloudtrace.agent
  roles/modelarmor.user
  roles/pubsub.publisher
  roles/spanner.databaseReader

full-shelf-ledger-sa:
  roles/cloudtrace.agent
  roles/spanner.databaseUser
```

The orchestrator Cloud Run ingress remains public at the platform invoker layer
and sensitive routes enforce their application/API-key or signed managed-callback
boundaries. The plan-ledger Cloud Run invoker binding is limited to the
orchestrator runtime and the human operator; it is not public. Neither runtime
has project Owner, Editor, Model Armor admin, or an administrator role.

## Resource delta and final inventory

WP12 created two Artifact Registry image versions and four Cloud Run revisions
(two initial image revisions plus two metadata-corrected revisions). It created
no new service, service account, IAM binding, database, topic, subscription,
Scheduler job, queue, key, or Model Armor template.

Final relevant inventory:

- two Cloud Run services, preserving the orchestrator / private ledger split;
- `full-shelf-main`, `full-shelf-audit-wp2-20260813`, and
  `full-shelf-audit-wp6-20260813`, all `READY`;
- topic `full-shelf-incidents`;
- subscriptions `full-shelf-incidents-sub` and
  `full-shelf-next-day-plan-sub`, both targeting the deployed orchestrator;
- enabled Scheduler jobs `full-shelf-daily-plan-job` (`05:30`) and
  `full-shelf-next-day-plan-job` (`17:00`);
- running Cloud Tasks queue `full-shelf-deadlines`;
- regional Model Armor template `full-shelf-recall-input-v1`;
- KMS approval key `full-shelf-keyring/approval-signer`.

## Exact reproduction commands

The local Google Cloud CLI currently needs its installed Python 3.14 runtime;
without `CLOUDSDK_PYTHON`, the local Python 3.9 launcher fails while loading the
Builds command.

```bash
git switch repair/backend-acceptance-20260813
git rev-parse HEAD
.venv/bin/python scripts/run_tests.py

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.14 \
gcloud spanner databases execute-sql full-shelf-main \
  --instance=fef-smoke-spanner --project=preflight-hackathon \
  --sql='SELECT COUNT(*) AS receipt_count FROM Receipts'

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.14 \
gcloud builds describe 0aaa79bb-87a0-4253-9334-c46472f204bc \
  --region=us-central1 --project=preflight-hackathon \
  --format='yaml(id,status,substitutions,results.images)'

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.14 \
gcloud builds describe f3366439-f107-4051-915d-4d944a652479 \
  --region=us-central1 --project=preflight-hackathon \
  --format='yaml(id,status,substitutions,results.images)'

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.14 \
gcloud run services describe full-shelf-orchestrator \
  --region=us-central1 --project=preflight-hackathon --format=json

CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.14 \
gcloud run services describe full-shelf-plan-ledger \
  --region=us-central1 --project=preflight-hackathon --format=json
```

Retrieve the judge key without printing it, then replay the non-mutating managed
paths. Use a fresh 32-hex trace ID for each request:

```bash
wp12_judge_key="$(CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.14 \
  gcloud secrets versions access latest \
  --secret=full-shelf-judge-api-key --project=preflight-hackathon)"

curl --silent --show-error --fail-with-body \
  'https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/custody/graph?scenario=canonical' \
  --header "X-Full-Shelf-API-Key: ${wp12_judge_key}" \
  --header 'traceparent: 00-<32_HEX_TRACE_ID>-0123456789abcdef-01'

curl --silent --show-error --fail-with-body \
  'https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/custody/graph?scenario=altered' \
  --header "X-Full-Shelf-API-Key: ${wp12_judge_key}" \
  --header 'traceparent: 00-<32_HEX_TRACE_ID>-0123456789abcdef-01'

curl --silent --show-error --fail-with-body --request POST \
  'https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/recall/extraction-preflight' \
  --header "X-Full-Shelf-API-Key: ${wp12_judge_key}" \
  --header 'Content-Type: application/json' \
  --header 'traceparent: 00-<32_HEX_TRACE_ID>-0123456789abcdef-01' \
  --data '{"notice_text":"<SYNTHETIC_SOURCE-ANCHORED_NOTICE>"}'
```

Read back a completed trace without printing the short-lived token:

```bash
wp12_access_token="$(CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.14 \
  gcloud auth print-access-token)"
curl --silent --show-error --fail-with-body \
  --header "Authorization: Bearer ${wp12_access_token}" \
  'https://cloudtrace.googleapis.com/v1/projects/preflight-hackathon/traces/<32_HEX_TRACE_ID>'
```

Read sanitized Model Armor proof while omitting `sanitizationInput`:

```bash
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.14 gcloud logging read \
  'logName="projects/preflight-hackathon/logs/modelarmor.googleapis.com%2Fsanitize_operations" AND timestamp>="<UTC_START>"' \
  --project=preflight-hackathon --limit=10 --format=json \
  | jq 'map({insertId,timestamp,resource:.resource.labels,labels,sanitizationResult:.jsonPayload.sanitizationResult})'
```

## Known failures and limitations

- No fresh mutating canonical hero-loop replay was run in WP12. Shared canonical
  authority is already in its governed post-recall state, and resetting or
  perturbing it for a builder replay would violate the evidence boundary. WP12
  replayed the canonical and altered interpretation and graph paths through
  deployed managed services with zero ledger mutation; prior package records
  contain the managed mutation-path testimony.
- The final evidence endpoint reports no active plan revision while the recall
  remains `PARTIALLY_CONTAINED`. This is a truthful result of the invalidated
  active revision, not a fabricated `rev08` success.
- Model Armor operation metadata warns that filter version V1 is projected to
  move from STABLE to LEGACY on `2026-09-01`. Current executions succeeded; the
  template version requires maintenance before that transition.
- The OpenTelemetry Cloud Trace exporter emits a deprecation warning. Managed
  export and API readback succeeded for every final correlation ID.
- Local `gcloud` defaults to an unsupported Python 3.9 and crashes for Cloud
  Builds commands; setting `CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.14`
  resolves the local CLI defect.
- The safe altered replay proves generalized managed input interpretation and
  variable-depth graph traversal. It does not claim a second deployed altered
  authoritative ledger universe.

## Claims requiring independent verification

An independent auditor must freshly reproduce the test count and zero canonical
receipt delta; image/SHA correspondence; runtime IAM and private ledger ingress;
all correlation IDs and managed logs; canonical and altered replay outputs;
prior WP1–WP10 managed mutation and refusal evidence; and the absence of an
alternate authoritative writer. Builder observations are not acceptance.

BUILDER HANDOFF COMPLETE — INDEPENDENT AUDIT REQUIRED
