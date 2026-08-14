# WP6 Scheduler, Pub/Sub, and continuity evidence

Date: 2026-08-13/14  
Builder status: `WP6 COMPLETE — READY FOR STRATEGY REVIEW`  
Acceptance authority: none. This is builder testimony until a different
auditor independently reproduces it.

## Result

The deployed managed path was observed as:

`Cloud Scheduler → Pub/Sub → audience-bound Google OIDC push → orchestrator →
authenticated plan-ledger → Spanner`.

A Scheduler-generated message created `PLAN-2026-08-14/rev01` dynamically from
its managed publish time. Spanner contains exactly one target plan, three
inherited constraints, one next-day coordinator, one accepted inbound event,
and one successful target idempotency receipt. The draft is not active and
requires human approval.

Evidence classifications:

- Code path, managed identity checks, and deterministic ledger policy:
  `STRUCTURALLY_VERIFIED`
- Complete safe suite: `MEASURED`
- Scheduler, Pub/Sub push, Cloud Run, private ledger, and Spanner execution:
  `OBSERVED_LIVE`
- Final WP6 acceptance: `NOT_PROVEN` pending independent reproduction

## Exact implementation and deployment

- Primary implementation commit:
  `d199c6881a9a1b6552692a76f1ddd0d1ffbb6fbf`
- Final corrective commits:
  `c05311ca9cfac4a600b595da939d98b405a15ed8`,
  `68ff68e43fefe3f77436f7a8851389371d7822ee`,
  `aa7e2e2ca311890ca312a660b50faeb1ebe6c7be`,
  `8c2e3c510a7d7bb1e34f41c82232c3c9b1bb00df`, and
  `619684d472d4a5ef1a928c1509d487f4e04275a1`
- Final Cloud Build: `63b65274-8b42-4537-8651-2c90ea1cba84`
  (`SUCCESS`)
- Build substitutions:
  `_GIT_SHA=619684d472d4a5ef1a928c1509d487f4e04275a1`,
  `_IMAGE_TAG=wp67-619684d472d4`
- Immutable image:
  `us-central1-docker.pkg.dev/preflight-hackathon/full-shelf-repo/orchestrator@sha256:4361f30a4e698506ece3b5c6161ef5739cb3709edff8c0dceadef520235af2e0`
- Deployed revision: `full-shelf-orchestrator-00036-xjl`
- Traffic: 100%
- Runtime identity:
  `full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com`
- Revision source label:
  `619684d472d4a5ef1a928c1509d487f4e04275a1`
- Container concurrency: 1; maximum instances: 20
- Ledger revision: `full-shelf-plan-ledger-00019-d4j`, immutable digest
  `sha256:1de12cc3f33d811a605e5780c114c589e5c81109d6ca1365cb56f585788d13f3`

The complete safe suite produced **114 passed, 0 failed, 18 warnings**.

## Managed configuration

Scheduler job `full-shelf-next-day-plan-job` is enabled in `us-central1` with
schedule `0 17 * * *`, time zone `America/Los_Angeles`, topic
`projects/preflight-hackathon/topics/full-shelf-incidents`, canonical body, and
attribute `event_type=PLAN_NEXT_DAY_REQUESTED`.

Filtered subscription `full-shelf-next-day-plan-sub` uses:

- filter `attributes.event_type="PLAN_NEXT_DAY_REQUESTED"`;
- push endpoint
  `https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/pubsub/push`;
- OIDC audience
  `https://full-shelf-orchestrator-620464070103.us-central1.run.app`;
- delivery identity
  `full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com`.

The original `full-shelf-incidents-sub` was temporarily switched to retained
pull mode to isolate a legacy retry backlog. No message was deleted. Its exact
authenticated push endpoint, audience, and identity were restored after the
acceptance run.

## Managed execution and authoritative result

- Pub/Sub message ID: `21435755642283426`
- Managed publish time: `2026-08-14T01:53:04.752Z`
- Accepted/committed at: `2026-08-14T02:04:35.756870Z`
- Initial successful Cloud Run request trace:
  `fef3e4434d0e0506f9d89aea65d42daf`
- Request log insert ID: `6a7e77b3000bd10672b18c29`
- Ledger application trace: `d0a9f10e76b70cbb83c8a22e35565287`
- Ledger receipt: `RCT-0914BC7309C85D7517A475E2`
- Ledger command: `CMD-NEXT-DAY-2026-08-14-REV01`
- Target idempotency key:
  `east-bay-food-bank:PLAN-2026-08-14:rev01:day-close`
- Mutations reported by the ledger: 6

Direct Spanner reconciliation:

```text
PlanRevisions: PLAN-2026-08-14 | rev01 | DRAFT_WITH_CONSTRAINTS
PlanConstraints:
  1 | LOT_MOVEMENT_BARRIER | LTC-4471 | ACTIVE
  2 | RECOVERY_PRIORITY | AG03 | 20 cases OPEN
  3 | ACKNOWLEDGMENT_HOLD | SITE-01 | 8 cases OPEN
Coordinator: COORD-2026-08-14 | DRAFT_WITH_CONSTRAINTS |
             HUMAN_APPROVAL_REQUIRED | rev01 | child_incidents=[]
InboundEvents: 21435755642283426 | PLAN_NEXT_DAY_REQUESTED | ACCEPTED
Target receipt cardinality: 1
Target plan cardinality: 1
Target constraint cardinality: 3
Target event cardinality: 1
```

`LTC-4471` is represented only as an active exclusion constraint. Confirmed
safe inventory was read from `LTC-5090` (`CLEAR_SAFE`), and operational fleet
capacity was read from authoritative vehicle rows. The recall incident remains
`PARTIALLY_CONTAINED`; it was not closed or transferred.

## Authentication and idempotency refusals

Deployed negative probes returned:

```text
No Authorization header: 401 MANAGED_CALLBACK_GOOGLE_ID_TOKEN_REQUIRED
Google token with wrong audience: 401 MANAGED_CALLBACK_GOOGLE_ID_TOKEN_INVALID
```

A second fresh Scheduler execution left target cardinalities at one plan,
three constraints, one coordinator, one inbound event, and one target receipt.
Several older retained day-close messages were later delivered when the legacy
subscription was restored. They produced separate `DENIED` receipts with zero
mutations because their expected revision was stale; they did not duplicate or
alter the target draft.

## Reproduction outline

```sh
gcloud scheduler jobs run full-shelf-next-day-plan-job \
  --project=preflight-hackathon --location=us-central1

gcloud spanner databases execute-sql full-shelf-main \
  --project=preflight-hackathon --instance=fef-smoke-spanner \
  --sql="SELECT * FROM PlanConstraints WHERE tenant_id='east-bay-food-bank' AND plan_id='PLAN-2026-08-14' ORDER BY priority"
```

## Limitations

- This is builder testimony, not independent acceptance.
- The shared topic contained retained legacy messages. Isolation was achieved
  with a new filtered authenticated subscription; the legacy path was restored.
- Cloud Trace exporter permission errors remain separate WP10 debt. Cloud Run
  request trace identifiers above are observed request-log traces, not claims
  of complete exported application traces.

WP6 COMPLETE — READY FOR STRATEGY REVIEW
