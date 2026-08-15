# Micro 4 — final builder handoff

Recorded: 2026-08-14 (America/Los_Angeles)

Runtime commit: `06e1d6ee6e584dfccce334fd11fb3b3f2e80fc16`

Classification: builder testimony; final independent audit required

This handoff records the completed Micro 4 builder boundary. It does not
declare backend acceptance. The documentation commit containing this handoff
is not a deployed runtime source revision.

## Acceptance-contract amendment

- `OBSERVED_LIVE` — unauthenticated `GET /` at the deployed orchestrator
  returns HTTP 200 and is Full Shelf's sole externally reachable public health
  endpoint.
- `OBSERVED_LIVE` — `GET /healthz` at the public Cloud Run boundary returns a
  Google-generated HTTP 404 before the container.
- `STRUCTURALLY_VERIFIED` — the application retains an explicitly classified
  `/healthz` handler in its exhaustive route-authentication matrix. It is not
  claimed as an observed-live public health endpoint.
- This is an acceptance-contract amendment only. No replacement endpoint,
  gateway, service, revision, IAM binding, or authentication exception was
  introduced.

## Immutable deployment and perimeter

| Service | Revision | Immutable image digest | Traffic |
|---|---|---|---:|
| `full-shelf-orchestrator` | `full-shelf-orchestrator-m4-06e1d6e` | `sha256:f1a9471570ef08883c75a88b440041343ddcfb69c459be1c708dfcc9874742c9` | 100% |
| `full-shelf-plan-ledger` | `full-shelf-plan-ledger-m4-06e1d6e` | `sha256:8ce72775627f638565caac82e823cb3e8c320f0fd314e2446b60665e830f6bda` | 100% |

- `OBSERVED_LIVE` — exactly two Full Shelf Cloud Run services exist.
- `OBSERVED_LIVE` — the orchestrator invoker policy contains the approved
  `allUsers roles/run.invoker` binding plus the orchestrator workload identity.
- `OBSERVED_LIVE` — the ledger invoker policy contains only the authorized
  orchestrator workload identity and no `allUsers` binding.
- The prior `full-shelf-orchestrator-00057-r2z` revision was not exposed; the
  public binding followed the new Micro 4 revision reaching 100% traffic and
  passing its pre-public controls.

## Route and identity qualification

- `STRUCTURALLY_VERIFIED` — every registered application route has exactly one
  policy classification: public health, human operator, managed callback,
  internal workload, or disabled/removed. Unregistered and removed framework
  routes fail closed.
- `OBSERVED_LIVE` — after the public invoker change, all sensitive routes
  rejected missing identity; disabled routes returned their contracted HTTP
  410; unclassified and removed framework paths returned HTTP 403.
- `OBSERVED_LIVE` — forged tokens, trusted-header impersonation, and the
  retired API key failed; managed callback and internal-workload positive
  controls accepted only their expected Google-signed workload identity.
- `OBSERVED_LIVE` — the ledger remained inaccessible at the Cloud Run boundary
  without its authorized orchestrator identity and independently rejected a
  wrong-audience application request.
- No Mark GIS login was requested or performed. The single positive human
  login remains reserved for the independent auditor.

## Verification and authoritative state

- `MEASURED` — the complete local suite passed 223 tests; the required safe
  suite passed 73 tests; the focused Micro 4 selection passed 57 tests.
- `MEASURED` — after this acceptance amendment, the contract and exhaustive
  route-authentication selection passed 31 tests. OpenAPI parsing and
  `git diff --check` also passed.
- `STRUCTURALLY_VERIFIED` — the isolated WP2 mutation replay passed against the
  noncanonical audit database.
- `MEASURED` — canonical state remained 18 receipts and 0 approvals.
- `MEASURED` — the reserved final-audit authority remained empty: 0 tenants,
  0 plans, 0 receipts, and 0 approvals.
- `OBSERVED_LIVE` — both reserved Scheduler jobs remained enabled with no
  `lastAttemptTime`. The builder did not trigger either job.

## Independent auditor obligations

Using the single reserved GIS login and the existing immutable deployment, the
independent auditor must still prove:

1. Mark's approval and Cloud KMS path.
2. Authenticated projection access.
3. Authenticated SSE connection, open-tail behavior, and cursor resume.
4. The fresh reserved managed hero loop.
5. All remaining negative identity and zero-mutation controls.

The auditor must independently reproduce the public `/` HTTP 200 and public
`/healthz` platform-boundary HTTP 404 expectations, route identity controls,
private-ledger boundary, service/IAM inventory, immutable image correspondence,
canonical `18/0`, and empty reserved authority. Builder observations are not
acceptance.

MICRO 4 COMPLETE — FINAL INDEPENDENT AUDIT REQUIRED
