# WP5 Gemini 3.5 through ADK evidence

Date: 2026-08-13  
Builder status: `WP5 COMPLETE — READY FOR STRATEGY REVIEW`  
Acceptance authority: none. This is builder testimony until a different
auditor independently reproduces it.

## Result

The deployed orchestrator screened synthetic notices through managed Model
Armor and then invoked `gemini-3.5-flash` through the load-bearing Google ADK
2.6.3 `Agent`/`Runner`. A complete notice produced a strict, source-anchored
five-field extraction and advanced only to deterministic policy review. An
ambiguous notice produced `MANUAL_REVIEW_REQUIRED`, set
`downstream_allowed=false`, and did not contact the ledger. No canonical
extraction fallback exists.

Evidence classifications:

- Code path, schema, model floor, and halt behavior: `STRUCTURALLY_VERIFIED`
- Complete safe test suite: `MEASURED`
- Final Cloud Run, Model Armor, and ADK/Gemini executions: `OBSERVED_LIVE`
- Cloud Logging identifier persistence and Spanner reconciliation:
  `OBSERVED_LIVE`
- Final WP5 acceptance: `NOT_PROVEN` pending independent reproduction

## Exact implementation and deployment

- Implementation commits:
  - `d65d1cf7934eab13235088443e7762bf69b7336c`
  - `e968bf45c515b2d51ce89eeb7e151990b5995bb9`
  - `61d4a183a8578734a0dc1803d9355da59b20313c`
- Final Cloud Build: `7831dc36-f3df-491d-b7a5-9cda785fb3ac`
  (`SUCCESS`)
- Build substitutions:
  `_GIT_SHA=61d4a183a8578734a0dc1803d9355da59b20313c`,
  `_IMAGE_TAG=wp5-61d4a183a857`
- Immutable image:
  `us-central1-docker.pkg.dev/preflight-hackathon/full-shelf-repo/orchestrator@sha256:bb571a8cfe9263dde4d9624b672fd98477680c81fdd17c52fd9fd98eaea624d4`
- Deployed revision: `full-shelf-orchestrator-00029-9cx`
- Traffic: 100% to that revision
- Runtime identity:
  `full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com`
- Revision labels:
  `full-shelf-source-revision=61d4a183a8578734a0dc1803d9355da59b20313c`,
  `full-shelf-work-package=wp5`
- Runtime configuration:
  `GEMINI_MODEL_ID=gemini-3.5-flash`, `VERTEX_LOCATION=global`

The build record and revision both report the same source SHA and immutable
digest. Reproduction commands:

```sh
gcloud builds submit --project=preflight-hackathon --region=us-central1 \
  --config=cloudbuild-orchestrator.yaml \
  --substitutions=_GIT_SHA=61d4a183a8578734a0dc1803d9355da59b20313c,_IMAGE_TAG=wp5-61d4a183a857 .

gcloud run services update full-shelf-orchestrator \
  --project=preflight-hackathon --region=us-central1 \
  --image=us-central1-docker.pkg.dev/preflight-hackathon/full-shelf-repo/orchestrator@sha256:bb571a8cfe9263dde4d9624b672fd98477680c81fdd17c52fd9fd98eaea624d4 \
  --update-env-vars=GEMINI_MODEL_ID=gemini-3.5-flash,VERTEX_LOCATION=global \
  --update-labels=full-shelf-source-revision=61d4a183a8578734a0dc1803d9355da59b20313c,full-shelf-work-package=wp5
```

## Load-bearing ADK boundary

`RecallExtractionAgent` is configured with the locked model and strict
Pydantic output schema. The only extraction invocation is ADK
`Runner.run_async`; there is no direct Gen AI or canonical fallback. The
orchestrator accepts exactly one final `STOP` response, validates it against
the same schema, verifies every value occurs in the screened source, and
requires the lot ID to appear in explicit lot context. ADK/model/schema/source
or identifier failures return manual review and halt before graph or ledger
work.

The returned IDs are actual ADK-created IDs. They are persisted in sanitized
Cloud Logging records. `InMemorySessionService` is named truthfully; it is not
claimed as managed ADK Sessions or authoritative state.

## Complete safe tests

Command:

```sh
pytest -q
```

Measured final result: **107 collected, 107 passed, 0 failed**. Sixteen
dependency/framework deprecation warnings were emitted; no test was skipped.
The suite covers strict schema failure, extra/missing fields, fabricated
values, ambiguous lot anchoring, model error, runner failure, missing or
multiple run IDs, truncated/non-STOP responses, and hero-loop termination
before graph and ledger behavior.

During remediation, the first full run found one static mutation-boundary test
failure caused by `dict.update`; the code was rewritten immutably. The first
managed image then failed closed because Gemini 3.5 spent the bounded output
budget on thinking and returned truncated JSON. Commit `e968bf45` disabled
thinking for this bounded extraction and preserved the budget for the schema.
Finally, a vague deployed notice revealed that substring anchoring alone could
misclassify a bulletin ID as a lot ID. Commit `61d4a183` added explicit lot
context validation. None of these intermediate runs is used as final proof.

## Final deployed reproduction

Retrieve the judge key without printing it and submit altered synthetic data:

```sh
wp5_judge_key=$(gcloud secrets versions access latest \
  --secret=full-shelf-judge-api-key --project=preflight-hackathon)

curl --silent --show-error --fail-with-body --request POST \
  'https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/recall/extraction-preflight' \
  --header "X-Full-Shelf-API-Key: ${wp5_judge_key}" \
  --header 'Content-Type: application/json' \
  --data '{"notice_text":"Supplier Safety Bulletin SB-8842: recall Lot ALT-8842 for Green Beans because of Listeria monocytogenes. Action: PAUSE_DISTRIBUTION."}'

curl --silent --show-error --fail-with-body --request POST \
  'https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/recall/extraction-preflight' \
  --header "X-Full-Shelf-API-Key: ${wp5_judge_key}" \
  --header 'Content-Type: application/json' \
  --data '{"notice_text":"Supplier bulletin SB-INCOMPLETE: a product may be affected. Pause distribution."}'
```

Sanitized observed outcomes:

| Case | App correlation | Cloud Run trace / request insert | ADK session / run / event | Result |
|---|---|---|---|---|
| Complete notice | `7c06590f1781d34a5614ef85805c0679` | `cf51e5d9fa325bb8cbacb81df201c293` / `6a7e5efb000e6d35d564297b` | `14c76c44-a3ee-4718-8e58-4ed83c763b24` / `e-3eb38f12-9ef3-498a-87f7-1a82034b1b65` / `52fd5519-da30-4cf7-bd9c-57d5308741be` | `EXTRACTION_VALIDATED`; next stage `DETERMINISTIC_POLICY_REVIEW`; 351 prompt, 100 output, 451 total tokens |
| Ambiguous notice | `93561dc6aaee60d31cec1917591a501a` | `034b804800d3153bf8039d7f76a4c5d6` / `6a7e5f0a000efa2d4474761c` | `4c8b77d4-000b-4e78-a7a8-31a97572c06e` / `e-5554903d-7697-4baa-8e98-3971e0811d11` / `523b3720-fc89-42f5-877b-b97b7fac47a8` | `MANUAL_REVIEW_REQUIRED`; `LOT_ANCHOR_VALIDATION_FAILED`; no next stage |

Both responses name `gemini-3.5-flash`, `google-adk/2.6.3`, the actual
session/run/event IDs, and `ledger_mutation_attempted=false`. Corresponding
stdout records have insert IDs `6a7e5efb000e6672cd05c6d5` and
`6a7e5f0a000ef4a2b3fd20a6`; each is labeled with the exact final source SHA,
WP5, and revision. Raw notice and raw model output are not logged.

The application correlation IDs above are not Cloud Trace IDs. The separately
listed trace IDs are from Cloud Run request logs. Cloud Trace did not retain a
retrievable complete trace for either request, and Vertex Data Access audit
logs were empty in the narrow execution window; neither is represented as
additional proof. The correlated deployed response, ADK-generated IDs,
sanitized revision log, pinned ADK-only code path, and managed revision are the
available builder evidence.

## Authoritative-state reconciliation

The final two probe routes explicitly stop before ledger mutation. A read of
plan-ledger request logs for `2026-08-14T00:18:55Z` through
`2026-08-14T00:19:30Z` returned **zero entries**. Direct Spanner counts before
WP5 probing and after the final probes were identical:

```text
Tenants 1; Coordinators 0; Lots 2; Vehicles 2; PlanRevisions 3; Orders 10;
Incidents 2; Receipts 3; Approvals 0; MovementBarriers 0;
RecoveryAllocations 0; RecoveryShortfalls 0; WorkItems 0;
CustodyNodes 6; CustodyEdges 5.
```

This proves no observed authoritative mutation from either final WP5 probe.

## Limitations carried forward

- This is builder testimony, not independent acceptance.
- Managed ADK Runtime/Sessions remain unavailable; the explicit local ADK
  session backend is non-authoritative.
- Cloud Trace did not yield a retrievable complete trace for these requests.
- Repeated Pub/Sub push requests returned 401 in adjacent logs. That is a WP6
  continuity defect and was not altered or characterized as solved in WP5.

WP5 COMPLETE — READY FOR STRATEGY REVIEW
