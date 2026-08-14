# WP11 — Isolated regression suite evidence

Recorded: `2026-08-14T03:26:30Z`  
Implementation commit: `a9ac78fb10563bfb9e6908a1cf70666679a8e7ba`  
Acceptance authority: none; this is builder testimony for independent reproduction.

## Isolation boundary

The complete pytest process is forced onto:

```text
projects/preflight-hackathon/instances/fef-smoke-spanner/databases/full-shelf-audit-wp6-20260813
```

The managed database was read-only inspected as `READY`. Root `conftest.py` sets
`SPANNER_DATABASE_ID` and `GRAPH_AUDIT_DATABASE_ID` before application modules are
collected. Collection and execution refuse `full-shelf-main`, an empty database ID,
or a database ID that is not explicitly named as an audit database.

The safe runner is:

```bash
.venv/bin/python scripts/run_tests.py
```

It uses the project virtual environment, deterministic Python path ordering, and the
same isolation checks as collection. The tests use fakes/mocks for managed adapters;
they do not make mutation calls to shared canonical authority.

## Exact results

```text
133 tests collected
133 passed
0 failed
0 skipped
15 warnings
2.62 seconds
```

The 15 warnings are dependency deprecation/future warnings: Cloud Trace exporter,
FastAPI `on_event`, a Python typing alias used by the Google SDK, and the
`google-cloud-storage` version transition. None was a skipped or failed test.

## Shared authoritative-state comparison

Read-only command run immediately before the suite and immediately after it:

```bash
gcloud spanner databases execute-sql full-shelf-main \
  --instance=fef-smoke-spanner \
  --project=preflight-hackathon \
  --sql='SELECT COUNT(*) AS receipt_count FROM Receipts'
```

Observed result:

| Moment | Canonical receipt count |
|---|---:|
| Before complete suite | 17 |
| After complete suite | 17 |
| Delta | 0 |

Classification: `OBSERVED_LIVE` for the two direct Spanner counts and audit-database
state; `STRUCTURALLY_VERIFIED` for the local isolation boundary and test coverage.

## Required coverage map

| Requirement | Reproducible coverage |
|---|---|
| Signed OIDC validation | `packages/domain/tests/test_identity.py`, `apps/plan-ledger/tests/test_ledger_auth.py` |
| Every invalid-token class | Missing/malformed bearer, signature verification, issuer, audience, expiry, missing/malformed subject/email/expiry, unverified email, unauthorized subject/email, and missing boundary configuration |
| Orchestrator write denial | `apps/orchestrator/tests/test_no_authoritative_writes.py`, `packages/domain/tests/test_single_mutation_authority.py` |
| Managed Model Armor and fail closed | `packages/domain/tests/test_model_armor.py`, `apps/orchestrator/tests/test_model_armor_halt.py` cover benign, managed match, HTTP 403, timeout, malformed response, failed/skipped filter, and pre-Gemini/pre-ledger halt |
| Gemini/ADK failure | `packages/domain/tests/test_adk_runner.py`, `apps/orchestrator/tests/test_adk_halt.py` |
| Scheduler/Pub/Sub idempotency | `apps/orchestrator/tests/test_next_day_plan.py` now proves identical managed message redelivery preserves the exact source event and publish-time inputs used by ledger idempotency |
| Cloud Tasks creation and delivery | `apps/orchestrator/tests/test_managed_callbacks.py` proves audience-bound task creation, authenticated delivery, ledger-only mutation, and deterministic redelivery idempotency key |
| Graph traversal over two topologies | `packages/domain/tests/test_graph_multihop.py`, `apps/orchestrator/tests/test_managed_graph.py` |
| SSE live tail and cursor | `apps/orchestrator/tests/test_sse_stream.py` |
| KMS tamper and expiration | `packages/domain/tests/test_kms_approval.py` |
| Evidence downgrades | `apps/orchestrator/tests/test_evidence_trace.py` |
| Canonical fallback prohibition | `packages/domain/tests/test_authoritative_read_failures.py`, managed graph empty-result refusal |
| Altered-scenario generality | `packages/domain/tests/test_altered_oracle.py`, altered graph, altered command, and tenant-isolation tests |

## Limitations

- WP11 is a safe isolated regression package, not a second managed end-to-end replay.
- The canonical database was queried only for before/after receipt counts; no WP11
  mutation was directed to it.
- These observations do not confer acceptance. An independent auditor must reproduce
  the suite and state comparison.
