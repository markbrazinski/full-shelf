# WP10 evidence, Trace, and provenance

Date: 2026-08-13/14  
Builder status: `WP10 COMPLETE — READY FOR STRATEGY REVIEW`  
Acceptance authority: none. This is builder testimony until a different
auditor independently reproduces it.

## Result

Both Cloud Run services now create real OpenTelemetry server spans, accept
valid W3C or Google trace parents, propagate W3C context across the private
ledger call and Cloud Tasks delivery, and persist the same correlation trace
ID on the deterministic receipt. The ledger rejects a command whose body
trace differs from the authenticated request execution trace.

The evidence endpoint no longer invents a random trace ID or promote configured
resources to `OBSERVED_LIVE`. It reports the active request span, performs live
Spanner and Graph reads, classifies each result independently, and returns
`FAILED`/`NOT_PROVEN` when evidence is missing.

Evidence classifications:

- Trace propagation, command binding, and downgrade tests:
  `STRUCTURALLY_VERIFIED`
- Complete safe suite (125 passed, 0 failed, 18 warnings): `MEASURED`
- Final evidence request, managed Trace readback, traced task/callback/ledger
  path, Spanner receipt, IAM, and deployed revisions: `OBSERVED_LIVE`
- Final WP10 acceptance: `NOT_PROVEN` pending independent reproduction

## Exact builds and deployments

Final orchestrator:

- Source: `65f247de49b52546942f21a9b602ebfc395d24de`
- Cloud Build: `5a89a95e-999d-491e-b5a7-730e6652c726`
- Digest:
  `sha256:e567938230786da9a1f5b71c04fb8585e55771c46022a4b7690b1e3466969f55`
- Revision: `full-shelf-orchestrator-00040-2hc`, 100% traffic
- Revision source label exactly matches the source above.

Final plan ledger:

- Source: `a20d9dc7a93166f024b9e1bd09f3d90944f4f997`
- Cloud Build: `a3f78520-9e6e-4d4a-b5f8-d284e1d47d59`
- Digest:
  `sha256:1336bbe769d65cfc02391234da854c6b20a1e94f09b13d48781ecb5f4eead466`
- Revision: `full-shelf-plan-ledger-00020-rls`, 100% traffic
- Revision source label exactly matches the source above.

Commit `65f247d` is an orchestrator-only correction after `a20d9dc`; the ledger
source is therefore truthfully recorded at `a20d9dc`. Both images carry the
OCI revision label supplied to their successful Cloud Build and are deployed
by immutable digest.

## Evidence endpoint trace proof

Final request trace: `444455556666777788889999aaaabbbb`.

The request supplied:

```text
traceparent: 00-444455556666777788889999aaaabbbb-0123456789abcdef-01
```

The deployed endpoint body returned the same trace ID, and response header
`X-Full-Shelf-Trace-Id` returned the same trace ID. It identified runtime
revision `full-shelf-orchestrator-00040-2hc`, source `65f247d...`, and digest
`sha256:e567...`.

Managed Cloud Trace API readback returned:

```text
projectId: preflight-hackathon
traceId: 444455556666777788889999aaaabbbb
span_count: 8
server span: orchestrator GET /api/v1/evidence/system
Spanner child spans: 6
```

The endpoint correctly left its own Cloud Trace classification `NOT_PROVEN`
with `PENDING_EXTERNAL_QUERY`, because the span cannot be exported and read
back until after the HTTP response finishes. This evidence record upgrades
only that completed, externally read-back execution to `OBSERVED_LIVE`.

## Fresh hero-loop resource correlation

The Site 01 escalation leg of the locked hero loop was exercised freshly under
trace `3333444455556666777788889999aaaa`:

```text
deployed decision:
  site01-3333444455556666777788889999aaaa
managed task:
  projects/preflight-hackathon/locations/us-central1/queues/
  full-shelf-deadlines/tasks/site01-3333444455556666777788889999aaaa
managed callback:
  /api/v1/incidents/site01-deadline
private ledger command:
  CMD-SITE01-site01-3333444455556666777788889999aaaa
authoritative receipt:
  RCT-E3A117925CF6FDA66B50970C
receipt trace:
  3333444455556666777788889999aaaa
status / mutations:
  SUCCESS / 2
committed at:
  2026-08-14T03:16:52.617468Z
```

Managed Cloud Trace readback for that same trace returned 14 spans, including:

- Cloud Run and application spans for the deployed scheduling decision;
- two Spanner precondition reads;
- Cloud Run and application spans for the automatic Cloud Tasks callback;
- Cloud Run and application spans for private
  `plan-ledger /api/v1/commands/execute`;
- the ledger Spanner transaction, session, reads, and commit.

This is end-to-end correlation of fresh hero-loop resources through the
authoritative receipt, not correlation inferred from configuration.

An earlier trace probe (`2222...`) exposed an extra strict payload field and
initially produced ledger 409 / callback 500 retries. Commit `65f247d` removed
that invalid ledger field while retaining header/body trace validation. The
managed retry later committed receipt `RCT-7439D341287D161D3D4E17FF` under the
same `2222...` trace. The final proof above uses the clean first-attempt
`3333...` execution.

## Truthful classifications and downgrade

For the successful final evidence request:

- the current orchestrator request, authoritative Spanner reads, latest
  receipt, latest inbound event, and managed graph query were
  `OBSERVED_LIVE`;
- Gemini and Model Armor configuration were `DESIGNED`, explicitly stating
  that configuration is not invocation evidence;
- Cloud Trace was `NOT_PROVEN` until the external managed readback above;
- build provenance was `DESIGNED` inside the process and independently
  verified with Cloud Run revision descriptions outside the process.

A deployed request for nonexistent tenant `wp10-missing-audit-tenant` returned:

```text
overall_classification: FAILED
failed_checks: [spanner_graph]
latest_ledger_receipt: NOT_PROVEN
latest_inbound_event: NOT_PROVEN
spanner_graph: FAILED / MANAGED_GRAPH_READ_UNAVAILABLE
Gemini configuration: DESIGNED
Model Armor configuration: DESIGNED
```

Thus missing managed evidence causes a downgrade and never becomes a success
claim.

## IAM delta and effective policy

The only WP10 IAM addition was
`roles/cloudtrace.agent` for
`full-shelf-ledger-sa@preflight-hackathon.iam.gserviceaccount.com`.

Final effective project roles observed for the two runtimes:

```text
orchestrator:
  roles/aiplatform.user
  roles/cloudtasks.enqueuer
  roles/cloudtrace.agent
  roles/modelarmor.user
  roles/pubsub.publisher
  roles/spanner.databaseReader

plan-ledger:
  roles/cloudtrace.agent
  roles/spanner.databaseUser
```

The orchestrator has no Owner, Editor, Model Armor administrator, or Spanner
writer role. The ledger has no administrator role.

## Limitations

- This is builder testimony, not independent acceptance.
- The fresh end-to-end execution is the Site 01 escalation leg of the hero
  loop; it does not reset or replay the already-terminal shared canonical
  incident.
- Endpoint classifications describe only what that request directly observed.
  Separate WP4–WP7 managed records remain the evidence for their prior
  Model Armor, ADK, Scheduler/Pub/Sub, and Cloud Tasks executions.
- OpenTelemetry Cloud Trace exporter deprecation warnings remain; export and
  readback succeeded, but migration is future maintenance rather than a WP10
  truth-boundary change.

WP10 COMPLETE — READY FOR STRATEGY REVIEW
