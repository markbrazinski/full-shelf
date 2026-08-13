# WP4 managed Model Armor evidence

Date: 2026-08-13  
Builder status: `WP4 COMPLETE — READY FOR STRATEGY REVIEW`  
Acceptance authority: none. This record is builder testimony until a different
auditor independently reproduces it.

## Result

The deployed orchestrator exercised the regional managed
`sanitizeUserPrompt` operation for an altered benign recall notice and an
altered injection notice. The benign input advanced only to the next
authorized boundary (`GEMINI_ADK_EXTRACTION`). The injection was rejected, the
WP4-only route did not invoke Gemini/ADK or the ledger, and canonical Spanner
state was unchanged.

Evidence classifications:

- Managed template and IAM configuration: `STRUCTURALLY_VERIFIED`
- Complete safe test suite: `MEASURED`
- Deployed Cloud Run and Model Armor executions: `OBSERVED_LIVE`
- Before/after Spanner row-count reconciliation: `OBSERVED_LIVE`
- Final WP4 acceptance: `NOT_PROVEN` pending independent reproduction

## Exact implementation and deployment

- Implementation commit:
  `483ee899492f61a61428373589979b168bec751f`
- Cloud Build:
  `39d9a962-f8ef-417e-adcf-24aa48e00f58` (`SUCCESS`)
- Build substitutions:
  `_GIT_SHA=483ee899492f61a61428373589979b168bec751f`,
  `_IMAGE_TAG=wp4-483ee899492f`
- Immutable image:
  `us-central1-docker.pkg.dev/preflight-hackathon/full-shelf-repo/orchestrator@sha256:92c939afd7f097d2e208c3f0c1e72c2a1de451dea5310b1ef355a71ed81831c1`
- Deployed revision: `full-shelf-orchestrator-00026-tnx`
- Traffic: 100% to `full-shelf-orchestrator-00026-tnx`
- Runtime identity:
  `full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com`
- Revision labels:
  `full-shelf-source-revision=483ee899492f61a61428373589979b168bec751f`,
  `full-shelf-work-package=wp4`
- Runtime configuration:
  `MODEL_ARMOR_LOCATION=us-central1`,
  `MODEL_ARMOR_TEMPLATE_ID=full-shelf-recall-input-v1`

Build command:

```sh
gcloud builds submit \
  --project=preflight-hackathon \
  --region=us-central1 \
  --config=cloudbuild-orchestrator.yaml \
  --substitutions=_GIT_SHA=483ee899492f61a61428373589979b168bec751f,_IMAGE_TAG=wp4-483ee899492f \
  .
```

Digest-pinned deployment command:

```sh
gcloud run services update full-shelf-orchestrator \
  --project=preflight-hackathon \
  --region=us-central1 \
  --image=us-central1-docker.pkg.dev/preflight-hackathon/full-shelf-repo/orchestrator@sha256:92c939afd7f097d2e208c3f0c1e72c2a1de451dea5310b1ef355a71ed81831c1 \
  --update-env-vars=MODEL_ARMOR_LOCATION=us-central1,MODEL_ARMOR_TEMPLATE_ID=full-shelf-recall-input-v1 \
  --update-labels=full-shelf-source-revision=483ee899492f61a61428373589979b168bec751f,full-shelf-work-package=wp4
```

The build record reports the same full source SHA and digest. The deployed
revision reports that digest both as its container image and
`status.imageDigest`.

## Managed resource and exact execution path

Template:

`projects/preflight-hackathon/locations/us-central1/templates/full-shelf-recall-input-v1`

Operation:

```text
POST https://modelarmor.us-central1.rep.googleapis.com/v1/projects/preflight-hackathon/locations/us-central1/templates/full-shelf-recall-input-v1:sanitizeUserPrompt
```

The managed template has prompt-injection/jailbreak filtering enabled at
`LOW_AND_ABOVE`, dangerous-content filtering at `MEDIUM_AND_ABOVE`, malicious
URI filtering enabled, `INSPECT_AND_BLOCK`, multilingual detection, and data
residency compliance. The regional template GET and both sanitizations were
observed live. A template GET is recorded only as configuration evidence; it
is not treated as sanitization evidence.

## Effective IAM

Commands:

```sh
gcloud projects get-ancestors preflight-hackathon --format=json

gcloud projects get-iam-policy preflight-hackathon \
  --flatten='bindings[].members' \
  --filter='bindings.members:full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com' \
  --format='json(bindings.role,bindings.members,bindings.condition)'

gcloud asset search-all-iam-policies \
  --scope=projects/preflight-hackathon \
  --query='policy:"full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com"' \
  --format='json(resource,policy)'

gcloud projects get-iam-policy preflight-hackathon \
  --flatten='bindings[].members' \
  --filter='bindings.role:roles/modelarmor.admin' \
  --format='json(bindings.role,bindings.members,bindings.condition)'

gcloud projects get-iam-policy preflight-hackathon \
  --flatten='bindings[].members' \
  --filter='bindings.members:allUsers OR bindings.members:allAuthenticatedUsers' \
  --format='json(bindings.role,bindings.members,bindings.condition)'

gcloud asset search-all-iam-policies \
  --scope=projects/preflight-hackathon \
  --query='resource:modelarmor' \
  --format='json(resource,policy)'
```

Observed effective result:

- The hierarchy contains only the project; there is no folder or organization
  ancestor from which this identity can inherit another binding.
- The orchestrator has `roles/modelarmor.user` at project scope.
- Its complete project-level role list contains no `roles/modelarmor.admin`,
  owner, editor, or custom role.
- Cloud Asset Inventory found the identity's resource-level bindings and none
  grants Model Armor administration.
- No `allUsers` or `allAuthenticatedUsers` project binding exists, and no
  Model Armor resource-level IAM policy was found.
- The sole `roles/modelarmor.admin` project binding belongs to the human
  operator `user:markbrazinski@gmail.com`, not the runtime service account.

Therefore the runtime identity has sanitize-user access and does not retain
administrator access through a direct, broad, resource-level, or inherited
binding.

## Complete safe tests

Commands:

```sh
PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python -m pytest --collect-only -q \
  packages/domain/tests apps/orchestrator/tests apps/plan-ledger/tests

PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python -m pytest -q \
  packages/domain/tests apps/orchestrator/tests apps/plan-ledger/tests
```

Measured result: **95 collected, 95 passed, 0 failed**. Eleven dependency and
framework deprecation/future warnings were emitted; no test was skipped or
failed.

The WP4 tests independently exercise these refusal conditions:

| Condition | Expected and measured behavior |
|---|---|
| HTTP 403 | `SERVICE_UNAVAILABLE`; upstream body omitted |
| Timeout | `SERVICE_UNAVAILABLE` |
| Malformed result | `SERVICE_UNAVAILABLE` |
| Filter `EXECUTION_SKIPPED` | `SERVICE_UNAVAILABLE` |
| Filter `EXECUTION_FAILED` | `SERVICE_UNAVAILABLE` |
| Managed `MATCH_FOUND` | `BLOCKED` |
| Any non-approved result in hero loop | halt before Gemini and ledger |

The deployed preflight tests replace Gemini and ledger functions with
assertion failures, proving either call would fail the suite. The committed
preflight handler itself contains no Gemini, ADK, Spanner, or ledger call.

## Deployed reproduction

The judge key remains in Secret Manager and is never printed or placed in the
request body. Reproduce with fresh noncanonical notices:

```sh
wp4_judge_key=$(gcloud secrets versions access latest \
  --secret=full-shelf-judge-api-key \
  --project=preflight-hackathon)

curl --silent --show-error --fail-with-body \
  --request POST \
  'https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/recall/model-armor-preflight' \
  --header "X-Full-Shelf-API-Key: ${wp4_judge_key}" \
  --header 'Content-Type: application/json' \
  --data '{"notice_text":"<ALTERED_BENIGN_RECALL_NOTICE>"}'

curl --silent --show-error --fail-with-body \
  --request POST \
  'https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/recall/model-armor-preflight' \
  --header "X-Full-Shelf-API-Key: ${wp4_judge_key}" \
  --header 'Content-Type: application/json' \
  --data '{"notice_text":"<ALTERED_PROMPT_INJECTION_NOTICE>"}'
```

Sanitized observed results:

| Input | App correlation | Cloud Run request trace | Cloud Run request/stdout insert IDs | Managed sanitize insert ID | Result |
|---|---|---|---|---|---|
| Altered benign | `b90e0e8095423cb3ef7074df53f9f1a0` | `6479e9ead69a90e18318c96a73eb5165` | `6a7e58a8000ce0e7d6560a68` / `6a7e58a8000cdced251164d1` | `706297a5-79f6-4fb1-a6ba-f651a6e7cfaa` | `NO_MATCH_FOUND`; `READY_FOR_GEMINI_ADK_EXTRACTION` |
| Altered injection | `85086430142b0e00bef1a9abd4f778a2` | `4989ef89efd0e457846a77fe0d8d19bf` | `6a7e58b2000207d2872103a0` / `6a7e58b20002045a1e3851e7` | `66eafd1d-2d16-4981-98d8-af23731e7e24` | `MATCH_FOUND` at high PI/jailbreak confidence; `REJECTED_BY_MODEL_ARMOR` |

The application identifiers are explicitly application request-correlation
IDs, not Cloud Trace IDs. The separate Cloud Run request traces above came
from the managed request logs. Model Armor sanitize-operation logs show
`SANITIZE_USER_PROMPT`, the exact regional template, successful filter
execution, and allow/block verdicts within 0.44 seconds of their respective
revision logs. Raw synthetic notice text is deliberately omitted here.

The revision's sanitized stdout records state:

```json
{"managed_operation":"sanitizeUserPrompt","gemini_adk_invoked":false,"ledger_mutation_attempted":false}
```

for both correlations, with benign status
`READY_FOR_GEMINI_ADK_EXTRACTION` and injection status
`REJECTED_BY_MODEL_ARMOR`.

A preliminary shell invocation incorrectly scoped the judge-key assignment and
received HTTP 401. It did not reach Model Armor and is not counted as managed
proof. The two corrected calls above returned HTTP 200 from the deployed
revision.

## Authoritative-state comparison

The same read-only union of `COUNT(*)` queries was executed immediately before
and after both deployed requests against:

`projects/preflight-hackathon/instances/fef-smoke-spanner/databases/full-shelf-main`

| Table | Before | After |
|---|---:|---:|
| Tenants | 1 | 1 |
| Coordinators | 0 | 0 |
| Lots | 2 | 2 |
| Vehicles | 2 | 2 |
| PlanRevisions | 3 | 3 |
| Orders | 10 | 10 |
| Incidents | 2 | 2 |
| Receipts | 3 | 3 |
| Approvals | 0 | 0 |
| MovementBarriers | 0 | 0 |
| RecoveryAllocations | 0 | 0 |
| RecoveryShortfalls | 0 | 0 |
| WorkItems | 0 | 0 |
| CustodyNodes | 6 | 6 |
| CustodyEdges | 5 | 5 |

The unchanged `Receipts` count directly confirms that the ledger recorded no
mutation receipt for either request. The unchanged authoritative table counts,
deployed route structure, and correlated `ledger_mutation_attempted=false` log
jointly support zero mutation from the rejected input. This application result
is not presented as proof of a Spanner mutation.

## Reproduction queries

```sh
gcloud run revisions describe full-shelf-orchestrator-00026-tnx \
  --project=preflight-hackathon --region=us-central1 --format=json

gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.revision_name="full-shelf-orchestrator-00026-tnx" AND httpRequest.requestUrl:"/api/v1/orchestrator/recall/model-armor-preflight"' \
  --project=preflight-hackathon --limit=10 --format=json

gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="full-shelf-orchestrator" AND textPayload:"<APP_CORRELATION_ID>"' \
  --project=preflight-hackathon --limit=20 --format=json

gcloud logging read \
  'logName="projects/preflight-hackathon/logs/modelarmor.googleapis.com%2Fsanitize_operations" AND timestamp>="2026-08-13T23:52:00Z"' \
  --project=preflight-hackathon --limit=20 --format=json
```

Use a narrow time window and sanitize exported logs: managed sanitize-operation
logs contain the submitted prompt text. Do not publish raw prompts, tokens, or
personal data.

## Limitations and handoff

- This is builder testimony, not independent acceptance.
- The managed response did not expose a server-generated request ID. The
  evidence therefore correlates application request IDs, Cloud Run request
  traces/insert IDs, exact revision and instance labels, timestamps, and Model
  Armor sanitize-log insert IDs without mislabeling one identifier as another.
- Model Armor reported its current filter version as stable and included a
  projected move to legacy on 2026-09-01. This did not affect the observed WP4
  executions, but the template version should be rechecked before a later
  production release.
- WP5 has not begun and no WP5 code is included in this package.

**WP4 COMPLETE — READY FOR STRATEGY REVIEW**
