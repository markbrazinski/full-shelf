# WP7 Cloud Tasks escalation evidence

Date: 2026-08-13/14  
Builder status: `WP7 COMPLETE — READY FOR STRATEGY REVIEW`  
Acceptance authority: none. This is builder testimony until a different
auditor independently reproduces it.

## Result

The deployed managed path was observed as:

`application decision → Cloud Tasks CreateTask → running queue → Google OIDC
callback → orchestrator callback policy → authenticated plan-ledger command →
Spanner receipt`.

The initial successful callback was the automatically dispatched managed task,
not a manual callback. A later manual request was used only to verify duplicate
idempotency after the managed success already existed.

Evidence classifications:

- Callback identity, task context, and ledger-only mutation path:
  `STRUCTURALLY_VERIFIED`
- Complete safe suite: `MEASURED`
- Deployed decision, real task resource, managed callback, and Spanner receipt:
  `OBSERVED_LIVE`
- Final WP7 acceptance: `NOT_PROVEN` pending independent reproduction

## Exact deployment

WP7 uses the same final source, build, image, revision, runtime identity, and
test result recorded by WP6:

- Source: `619684d472d4a5ef1a928c1509d487f4e04275a1`
- Cloud Build: `63b65274-8b42-4537-8651-2c90ea1cba84`
- Image digest:
  `sha256:4361f30a4e698506ece3b5c6161ef5739cb3709edff8c0dceadef520235af2e0`
- Revision: `full-shelf-orchestrator-00036-xjl` at 100% traffic
- Tests: 114 passed, 0 failed, 18 warnings

Queue `projects/preflight-hackathon/locations/us-central1/queues/full-shelf-deadlines`
was observed `RUNNING`.

## Managed execution

Before the deployed decision, direct Spanner counts for
`SITE01_ACKNOWLEDGMENT_DEADLINE` events and `RECORD_ACKNOWLEDGMENT_HOLD`
receipts were both zero.

The judge-protected deployed decision route returned:

```text
decision_id: site01-6f611b539351b7c6655ee99d2de880d6
task_name: projects/preflight-hackathon/locations/us-central1/queues/
           full-shelf-deadlines/tasks/site01-6f611b539351b7c6655ee99d2de880d6
target: https://full-shelf-orchestrator-620464070103.us-central1.run.app/
        api/v1/incidents/site01-deadline
audience: https://full-shelf-orchestrator-620464070103.us-central1.run.app
identity: full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com
```

The sanitized structured creation record is Cloud Logging insert
`6a7e781c0002b313171410c0`. The deployed decision request succeeded at
`2026-08-14T02:06:19.987341Z` with Cloud Run trace
`c5b4aeac8e319092a8b7a5669b3a8f21`. The callback began at
`2026-08-14T02:06:20.243958Z`, succeeded with HTTP 200, and has Cloud Run
trace `d05bdc027d78d4d5b625b6acfce91ae5`.

The sub-second sequence, real fully qualified task returned by CreateTask,
Cloud Tasks delivery headers, and verified Google claims persisted by the
ledger form the managed-delivery evidence. The project did not emit a separate
Cloud Tasks Data Access audit entry for CreateTask in this interval; none is
invented.

## Authoritative result

Direct Spanner reconciliation after the managed callback:

```text
Inbound event: site01-6f611b539351b7c6655ee99d2de880d6
Event type: SITE01_ACKNOWLEDGMENT_DEADLINE
Event status: ACCEPTED
Delivery subject: 105774551577568412756
Delivery email: full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com
Delivery audience: https://full-shelf-orchestrator-620464070103.us-central1.run.app
Ledger receipt: RCT-19F3D0BAA928D4849F77E123
Ledger trace: 4a9accd3ef749e44eafcb3662fa37014
Ledger command: RECORD_ACKNOWLEDGMENT_HOLD
Mutations: 2
Hold: INC-RECALL-01-HOLD-SITE01 | ACKNOWLEDGMENT_HOLD_ACTIVE |
      LTC-4471 | SITE-01 | 8 unconfirmed cases | PARTIALLY_CONTAINED
```

The callback has no Spanner write code. Its only mutation action is the
authenticated `RECORD_ACKNOWLEDGMENT_HOLD` command to private `plan-ledger`.

## Rejection and duplicate matrix

Deployed results:

```text
No Authorization header: 401 MANAGED_CALLBACK_GOOGLE_ID_TOKEN_REQUIRED
Google token with wrong audience: 401 MANAGED_CALLBACK_GOOGLE_ID_TOKEN_INVALID
Valid Google identity, forged task-name/body pairing:
  400 CLOUD_TASK_NAME_PAYLOAD_MISMATCH
Supplemental replay of the real task context:
  200, idempotent_replay=true, original receipt RCT-19F3D0BAA928D4849F77E123
```

After all probes, authoritative cardinality remained one accepted deadline
event and one hold receipt. The rejected requests never reached the ledger.

## Limitations

- This is builder testimony, not independent acceptance.
- Cloud Tasks Data Access audit logging did not produce a CreateTask audit row;
  the evidence uses the real task resource returned by the managed API, the
  immediate authenticated callback request, persisted Google claims, and the
  ledger receipt.
- The successful initial proof is the automatic managed callback. The manual
  duplicate replay is explicitly supplemental and is not used as task-delivery
  proof.

WP7 COMPLETE — READY FOR STRATEGY REVIEW
