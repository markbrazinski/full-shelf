# Work Package 0 — resolved baseline and repair map

Recorded: `2026-08-13T21:01:33Z`  
Evidence classification: repository facts are `STRUCTURALLY_VERIFIED`; managed-resource facts are read-only observations and do not prove successful execution.

## Gate and authority resolution

WP0 acceptance requires an exact clean baseline, deployed revision and IAM inventory, complete mutation/caller maps, a bounded file/resource repair map, and preservation of the two-service topology.

The authority packet was read completely in the commission's required order. `05_AUTHORITY_RESOLUTION_MEMO.md` controls the previously ambiguous points:

- Official event: Google All Things Agentic Hackathon, Fortified Enterprise Fleet track.
- Build Book v1.1 is canonical.
- Current recall positions are `24 + 22 + 20 + 10 + 8 + 12 = 96`; Agency 01's historical 18-case receipt is not a current-position subtotal.
- The approval binds the complete `rev07` to `rev08` diff, both order actions and quantities, plan and truck-incident IDs, a verified human principal, expiry, diff hash, and KMS key version.
- The full recall lifecycle is `DETECTED → SCOPING → CONTAINMENT_IN_PROGRESS → PARTIALLY_CONTAINED → CONTAINED → CLOSED`.
- Model Armor must use an actual supported managed sanitization operation; a floor-setting GET and local string matching are invalid.
- Human approval uses a Google Identity Services ID token verified by immutable `sub`; workload calls use separate Cloud Run OIDC tokens.
- The orchestrator remains public, but Pub/Sub and Cloud Tasks callbacks require application-level Google OIDC verification with exact audience and service identity.
- All callback mutations cross the private ledger; no third service is authorized.
- Configuration must be explicit and absent required values must fail closed.
- Tests and migrations must be isolated from the shared canonical data.

Repository ADR 003 contains a stale one-action `v1 → v2` approval description, and ADR 004 contains a stale regional floor-setting GET. They are repair targets, not controlling authority. The non-authoritative Antigravity plan also uses a stale recall subtotal; it is explicitly rejected in favor of the memo.

## Repository baseline

- Starting branch: `main`
- Audited and current HEAD before branch creation: `bfd1e1040824da379d69add8755682bc8eafebd6`
- Worktree before branch creation: clean
- Repair branch: `repair/backend-acceptance-20260813`, created directly from the audited SHA
- Topology: exactly two services; no third service is proposed

## Deployed baseline

Project `preflight-hackathon`, region `us-central1`:

| Service | Revision | Image digest | Runtime identity | Invoker state |
|---|---|---|---|---|
| `full-shelf-orchestrator` | `full-shelf-orchestrator-00022-l9w` | `sha256:211d5b47e0700607f79c2fe73859831f035d71d157570ff1623b0184acc35198` | `full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com` | `allUsers` |
| `full-shelf-plan-ledger` | `full-shelf-plan-ledger-00014-q6l` | `sha256:1b6d17658e5fc7f92b2a12357a7cbe979197bf230fcaab47c3f379e8b3bf4614` | `full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com` | `allUsers`, orchestrator SA, audit user |

Both revisions use mutable `v1` image tags and have no Git-SHA provenance. Both services have ingress `all`; only the ledger's IAM exposure violates the intended boundary.

Existing service identities:

- Orchestrator SA immutable subject: `105774551577568412756`
- Ledger SA: `full-shelf-ledger-sa@preflight-hackathon.iam.gserviceaccount.com`
- Ledger SA immutable subject: `101789932459049570050`

Project IAM currently grants the orchestrator SA `roles/owner`, `roles/spanner.databaseUser`, and `roles/spanner.databaseReader`. The existing ledger SA has `roles/spanner.databaseUser` but is not the deployed ledger identity.

Supporting resources observed:

- Spanner: instance `fef-smoke-spanner`, database `full-shelf-main`
- Pub/Sub: topic `full-shelf-incidents`; push subscription `full-shelf-incidents-sub`
- Push endpoint: orchestrator `/api/v1/orchestrator/pubsub/push`
- Push identity: orchestrator SA; explicit audience absent
- Scheduler: `full-shelf-daily-plan-job` and `full-shelf-next-day-plan-job`, enabled
- Cloud Tasks queue: `full-shelf-deadlines`, running; no execution proof inferred
- KMS: asymmetric signing key `projects/preflight-hackathon/locations/us-central1/keyRings/full-shelf-keyring/cryptoKeys/approval-signer`

## Authoritative mutation map

Direct orchestrator writes, all prohibited and assigned to WP2:

| Route/path | Current mutation |
|---|---|
| Daily-plan generation failure | Direct coordinator failure update |
| `/coordinator/persist-waiting` | Direct coordinator upsert |
| `/incidents/site01-deadline` | Direct incident deadline/status update |
| `/pubsub/push` | Direct coordinator and incident writes |
| Recall hero loop | Direct recall terminal-state update |
| `/demo/reset` and seed/replay path | Direct plan, incident, coordinator, and receipt changes |

Ledger mutation paths, retained but to be authenticated in WP1 and redesigned deterministically in WP2–WP3:

- Daily and next-day plan save
- Action execution and rev08 activation
- Recall incident creation
- Safe-stock allocation
- Site 01 containment refusal and deadline callback
- Startup fixture seeding (must be removed from production)

## Caller and callback identity map

| Caller | Target | Current behavior | Required state |
|---|---|---|---|
| Public/browser | Orchestrator public routes | Judge API key on some routes; no GIS human identity | Public surface retained; consequential approval later requires verified GIS identity |
| Orchestrator SA | Ledger | Metadata token with ledger URL as audience on one path; other HTTP calls send no token | Every ledger call has a verified Google token with explicit exact audience |
| Pub/Sub push | Orchestrator callback | Google OIDC configured without explicit audience; deployed delivery returns 401 | Explicit callback audience; verify signature, issuer, expiry, audience, and orchestrator SA subject/email |
| Cloud Tasks | Orchestrator callback | Header trust/no verified token; producer absent | Explicit callback audience and task delivery SA; callback verifies token before logic |
| Orchestrator callback | Ledger | Some direct unauthenticated calls and some direct Spanner writes | Authenticated ledger command only |
| Direct external caller | Ledger | Public IAM and unverified JWT decode | Rejected by Cloud Run IAM and by application verification |

## Package impact map

| Package | Principal repository files | Managed resources |
|---|---|---|
| WP1 | shared identity module; both service entrypoints; requirements; `.env.example`; auth tests | Cloud Run ledger IAM/runtime SA; project IAM; explicit service audience |
| WP2 | both entrypoints; deterministic command/domain modules; schema/migrations; tests | Spanner schema and ledger deployment |
| WP3 | KMS/approval domain; ledger and orchestrator approval routes; ADR 003; tests | KMS IAM/key-version use; GIS OAuth client configuration |
| WP4 | recall security adapter; orchestrator; ADR 004; tests | Model Armor template/resource and IAM |
| WP5 | ADK recall extraction; orchestrator; tests | Vertex AI/Gemini execution configuration |
| WP6 | coordinator/planning domain; callbacks; tests | Scheduler, Pub/Sub subscription OIDC/audience |
| WP7 | tasks producer/callback/ledger command; tests | Tasks queue, delivery identity, explicit audience |
| WP8 | graph/reconciliation domain; schema/fixtures; tests | Spanner Graph data and queries |
| WP9 | projection stream and event repository; tests | Spanner event/receipt ordering |
| WP10 | evidence/trace modules; build configs; tests | Cloud Trace, Artifact Registry, Cloud Build, Cloud Run labels/revisions |
| WP11 | isolated test configuration, fixtures, regression tests | Isolated audit database/tenant or emulator only |
| WP12 | deployment/runbooks/evidence manifest | The same two Cloud Run services and existing managed dependencies |

## Exact inspection commands and observations

Commands were executed read-only except branch creation:

```text
git status --short --branch
git rev-parse HEAD
git switch -c repair/backend-acceptance-20260813 bfd1e1040824da379d69add8755682bc8eafebd6
gcloud run services describe <service> --region us-central1 --project preflight-hackathon --format=json
gcloud run revisions describe <revision> --region us-central1 --project preflight-hackathon --format=json
gcloud run services get-iam-policy <service> --region us-central1 --project preflight-hackathon --format=json
gcloud projects get-iam-policy preflight-hackathon --format=json
gcloud iam service-accounts describe <service-account> --project preflight-hackathon --format=json
gcloud pubsub subscriptions describe full-shelf-incidents-sub --project preflight-hackathon --format=json
gcloud scheduler jobs list --location us-central1 --project preflight-hackathon --format=json
gcloud tasks queues describe full-shelf-deadlines --location us-central1 --project preflight-hackathon --format=json
gcloud kms keys describe approval-signer --keyring full-shelf-keyring --location us-central1 --project preflight-hackathon --format=json
rg -n "run_in_transaction|execute_update|insert_or_update|database\\.|snapshot\\(|transaction" apps/orchestrator/src apps/plan-ledger/src
rg -n "Authorization|Bearer|decode_caller|fetch_id_token|identity|oidc|pubsub|callback|CloudTasks|create_task|PLAN_LEDGER" apps/orchestrator/src apps/plan-ledger/src
```

The first Cloud Run inspection attempt used the system Python 3.9 and failed in the local CLI with `CommandLoadFailure`; rerunning with `CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.12` succeeded. This was a local CLI compatibility issue, not a managed-service failure.

## WP0 result and WP1 gate

WP0 is `LOCALLY VERIFIED`; no managed execution claim is made. WP1 begins with these acceptance conditions:

- Missing, unsigned, wrong-issuer, wrong-audience, expired, and unauthorized-subject credentials fail before route logic.
- Correct orchestrator workload identity reaches an allowed ledger command.
- The ledger uses the distinct ledger SA and is not invokable by `allUsers`.
- The orchestrator SA has neither Owner nor Spanner writer permission.
- A direct orchestrator-runtime Spanner mutation returns permission denied.

If any WP1 acceptance condition fails, later packages must not begin.
