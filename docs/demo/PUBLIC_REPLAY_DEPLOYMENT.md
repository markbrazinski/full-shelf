# Public replay deployment

> **DATED NOTE — 2026-08-31.** Two statements below have changed since this
> document was written:
>
> - *"Full Shelf still has exactly the two Cloud Run services `AGENTS.md` locks
>   in"* — still true of **authoritative** services, but an authenticated judge
>   environment has since been deployed alongside them under amendment CR-001.
>   See *Deployed services* in `README.md`.
> - *"the project's key currently has no HTTP-referrer restriction"* — the Maps
>   Platform key has since been restricted to the judge/replay hosts plus
>   localhost, and scoped to the Maps JavaScript backend only. The reasoning for
>   keeping the key out of the anonymous replay bundle is unchanged.
>
> The rest of this document remains accurate for `full-shelf-demo-replay`.


The hosted deterministic replay judges use: what it is, how it was built and
deployed, how to verify it, what it costs, and how to take it down.

**Public URL** — <https://full-shelf-demo-replay-620464070103.us-central1.run.app>

No sign-in. No credentials. Nothing to install.

## What this service is, and is not

It serves one thing: a **replay of a previously completed operating day**,
Friday 2026-08-14, from committed fixtures. Every visitor gets their own
session and drives it themselves.

It is **not** part of the authoritative product architecture. Full Shelf still
has exactly the two Cloud Run services `AGENTS.md` locks in —
`full-shelf-orchestrator` and `full-shelf-plan-ledger` — and this replay is
neither of them. It owns no authoritative state, so there is nothing in it to
mutate.

Everything it emits is classified `SYNTHETIC_TEST`, states so in every
response, and says so on screen: the header carries a
`REPLAY · RECORDED RUN` badge in judge builds.

### Structural isolation

The container cannot reach a Google service, because nothing in it can make a
network call. The whole deployed Python surface is
`public_server.py`, `session.py`, `events.py`, `locations.py`, and their
imports are stdlib only — `json`, `os`, `re`, `pathlib`, `threading`,
`copy`, `uuid`, `hashlib`, `mimetypes`, `datetime`, `zoneinfo`,
`http.server`, and `urllib.parse` (string parsing, not networking).

No Google client library, no HTTP client, no credential read, no disk write.
The runtime service account holds **zero project IAM roles**, so even a
hypothetical call would have no authority behind it.

| Reachable from the replay | |
|---|---|
| Gemini / Vertex AI | no — no client, no role |
| ADK / orchestrator | no — no client, no role |
| Spanner | no — no client, no role |
| Cloud KMS | no — no client, no role |
| Pub/Sub, Cloud Tasks | no — no client, no role |
| Plan ledger | no — no client, no role |

## Topology

One container, one origin, two surfaces:

```
                    https://full-shelf-demo-replay-…run.app
                                    │
                        Cloud Run (us-central1)
                     full-shelf-demo-replay, port 8080
                                    │
                 ┌──────────────────┴──────────────────┐
                 │       public_server.py (stdlib)     │
                 │                                     │
                 │  GET  /            built React SPA  │
                 │  GET  /assets/*    hashed bundles   │
                 │  GET  /api/healthz readiness        │
                 │  *    /api/v1/replay/…  replay API  │
                 │                                     │
                 │  session.py  ← the one state machine│
                 │  fixtures/   ← committed projections│
                 └─────────────────────────────────────┘
```

Serving the frontend and the replay API from the **same origin** is what
removes CORS from the deployment entirely: the page calls `/api/v1/replay/…`
on its own host, so no cross-origin grant exists to get wrong.

`session.py` is shared verbatim with the local development runtime, so the
canonical event contract — ordering, the human approval gate, the terminal
state — is enforced by one implementation, not a deployment copy that could
drift.

### Why a separate transport file

`tools/replay/runtime_server.py` (local development) asserts that it can never
leave loopback. That is a safety property worth keeping literally true, so the
deployment transport that binds `0.0.0.0` is a **different file** rather than a
flag on that one. Both delegate every ordering decision to `session.py`.

## Build and deploy

Both steps are explicit. A build never moves public traffic on its own.

```bash
cd /path/to/full-shelf
SHA=$(git rev-parse HEAD)

# 1. Build. Tags the image with the full Git SHA.
gcloud builds submit \
  --config=cloudbuild-demo-replay.yaml \
  --substitutions=_GIT_SHA=$SHA .

# 2. Resolve the immutable digest and deploy BY DIGEST, never by tag.
DIGEST=$(gcloud artifacts docker images describe \
  us-central1-docker.pkg.dev/preflight-hackathon/full-shelf-repo/demo-replay:$SHA \
  --format="value(image_summary.digest)")

gcloud run deploy full-shelf-demo-replay \
  --image="us-central1-docker.pkg.dev/preflight-hackathon/full-shelf-repo/demo-replay@$DIGEST" \
  --region=us-central1 --platform=managed \
  --service-account=full-shelf-replay-sa@preflight-hackathon.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --cpu=1 --memory=512Mi --concurrency=20 \
  --min=1 --max-instances=2 \
  --cpu-throttling --cpu-boost --port=8080 --session-affinity \
  --set-env-vars="FULL_SHELF_JUDGE_MODE=1,FULL_SHELF_STATIC_ROOT=/app/static" \
  --labels="component=demo-replay,classification=synthetic-test,git-sha=$SHA" \
  --revision-suffix="v-${SHA:0:7}"
```

### The browser Maps key is deliberately absent

Vite inlines every `VITE_*` value into the public JavaScript bundle. Building
with a Maps key would publish that key to anyone who views source — and the
project's key currently has **no HTTP-referrer restriction** and is enabled for
~35 Maps APIs, several of them billable.

So the deployment Dockerfile sets `VITE_GOOGLE_MAPS_API_KEY=""` explicitly.
Without a key the map renders Full Shelf's truthful deterministic SVG
schematic, which is an existing, asserted product path — not a degraded
placeholder. Local development with a real key is unaffected.

To use a real basemap later: restrict the key to the `*.run.app` referrer and
the Maps JavaScript API only, then rebuild passing it as a build arg. Do not
deploy an unrestricted key.

## Configuration

| Setting | Value | Verified |
|---|---|---|
| Service-level min instances | `1` | `metadata.annotations."run.googleapis.com/minScale"` |
| Revision-level min instances | **absent** | no `autoscaling.knative.dev/minScale` |
| Max instances | `2` | `autoscaling.knative.dev/maxScale` |
| CPU | `1` | |
| Memory | `512Mi` | |
| Concurrency | `20` | |
| Startup CPU boost | enabled | `run.googleapis.com/startup-cpu-boost=true` |
| Billing | request-based | `run.googleapis.com/cpu-throttling=true` |
| Session affinity | enabled | `run.googleapis.com/sessionAffinity=true` |
| Access | `allUsers` → `roles/run.invoker` | |
| Service account | `full-shelf-replay-sa` (zero project roles) | |
| Traffic | 100% to one revision, no tags | |

Minimum instances is set at the **service** level, so exactly one warm
instance is kept — a revision-level minimum would keep an instance warm per
revision and quietly multiply the idle cost.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | supplied by Cloud Run | listener port; the container binds whatever it is given |
| `FULL_SHELF_JUDGE_MODE` | `1` | serves the judge surface and the replay disclosure |
| `FULL_SHELF_STATIC_ROOT` | `/app/static` | built frontend inside the image |
| `FULL_SHELF_STREAM_IDLE_SECONDS` | `20` | how long a caught-up SSE stream is held |
| `FULL_SHELF_MAX_SESSIONS` | `400` | in-memory session cap; oldest retired first |

**`FULL_SHELF_STREAM_IDLE_SECONDS` is load-bearing.** Concurrency 20 across at
most 2 instances is 40 request slots, and each replay holds one for its SSE
stream. At 90s, a burst of visits accumulated abandoned streams faster than
they expired, exhausted the slots, and left new visitors stuck at the opening
event while the runtime had already advanced. At 20s the same burst passes
repeatedly. Active viewers are never cut: deterministic pacing commits an
event well inside the window, and a caught-up stream resumes from its cursor
via `Last-Event-ID` with no event missed or duplicated.

## Health check

```bash
curl https://full-shelf-demo-replay-620464070103.us-central1.run.app/api/healthz
```

```json
{
  "status": "ok",
  "service": "full-shelf-demo-replay",
  "mode": "DETERMINISTIC_REPLAY",
  "judge_mode": true,
  "classification": "SYNTHETIC_TEST",
  "scenario_id": "full-shelf-friday-2026-08-14"
}
```

It is answered before any session lookup: it mints no session and advances no
cursor, so probing it forever changes nothing.

> The path is `/api/healthz`, not `/healthz`. Google Frontend intercepts
> `/healthz` on Cloud Run and returns its own 404 before the request reaches
> the container. The bare spelling still works off-platform.

## Judge instructions

1. Open the URL. The replay starts on its own — no button to find, nothing to
   configure.
2. **Start** is automatic: the page holds the opening frame for four seconds,
   then Friday's completed plan begins to move.
3. **Restart** is a browser refresh, which mints a brand-new isolated session
   at the opening event.
4. Two moments wait for a human, by design:
   - **Approve the repair** — the truck-failure recovery does not proceed
     until the operator approves it. Nothing advances past it on a timer.
   - **Open Incidents** — when the recall notice lands, the response waits
     until the judge chooses to work it.
5. Expected terminal outcome: **`PARTIALLY_CONTAINED`**, not a clean
   resolution. 96 physical cases traced, 88 confirmed, **Site 01's 8 cases
   explicitly unconfirmed**, 40 safe replacements allocated, Agency 03 keeping
   a truthful 20-case shortfall, closure **refused**, and Saturday's draft
   carried forward as `DRAFT_WITH_CONSTRAINTS — HUMAN APPROVAL REQUIRED`.
   The refusal is the point: the system declines to claim containment it
   cannot evidence.

Exploring is safe. Navigation only selects views; it never advances, rewinds,
or skips the replay, and one judge's session cannot affect another's.

## Verification

The adversarial suite runs against the deployed service, not a local mock:

```bash
cd apps/web
FS_BASE_URL="https://full-shelf-demo-replay-620464070103.us-central1.run.app" \
  npx playwright test -c playwright.deployed.config.ts
```

24 cases: anonymous entry, two isolated browser contexts, refresh at eight
stage boundaries, Back/Forward, hammering Incidents through the truck-failure
transition, ten consecutive complete replays, slow and stale projection
responses, rejected backwards cursor movement, no `rev08` authority before
approval, no recall state before intake, and no full containment while custody
is unconfirmed.

Result on the live public URL: **24/24, three consecutive runs (72/72).**

## Cost

Request-based billing with one warm instance at 1 vCPU / 512MiB.

| | Estimate |
|---|---|
| Idle, per day | ~$0.32 |
| Two weeks of judging | ~$4.50 |
| Thirty days | ~$9.60 |

Judge traffic adds little: requests are small, the CPU is throttled between
them, and the cap of 2 instances bounds the worst case at roughly twice idle.
Before credits and free tier. **Scale to zero after judging** (below) and the
idle cost goes away.

## Rollback

Non-destructive. Traffic is pinned to a named revision; nothing is deleted.

```bash
# What is currently serving, and what else exists.
gcloud run services describe full-shelf-demo-replay --region=us-central1 \
  --format="value(status.traffic)"
gcloud run revisions list --service=full-shelf-demo-replay --region=us-central1

# Roll back to a known-good revision.
gcloud run services update-traffic full-shelf-demo-replay \
  --region=us-central1 --to-revisions=full-shelf-demo-replay-v-dc12105=100
```

Verified rollback point: **`full-shelf-demo-replay-v-dc12105`**, digest
`sha256:7900c970ff310f856fb0cdfb3dbc458c9e58e5b3909b526abe203ff24c947903`,
the revision that passed 72/72 publicly.

## After judging

**Scale to zero** — keeps the URL working, removes the idle cost. First
request afterwards pays a cold start (a few seconds; startup boost is on).

```bash
gcloud run services update full-shelf-demo-replay \
  --region=us-central1 --min-instances=0
```

**Delete the service** — frees the URL permanently.

```bash
gcloud run services delete full-shelf-demo-replay --region=us-central1

# Optional, once nothing needs the images or the identity:
gcloud artifacts docker images delete \
  us-central1-docker.pkg.dev/preflight-hackathon/full-shelf-repo/demo-replay \
  --delete-tags
gcloud iam service-accounts delete \
  full-shelf-replay-sa@preflight-hackathon.iam.gserviceaccount.com
```

Neither command touches `full-shelf-orchestrator`, `full-shelf-plan-ledger`,
Spanner, or any product data.

## Known limitations

- **Sessions are in-memory.** They do not survive an instance recycling. An
  unknown-but-well-formed session id is adopted at the opening boundary rather
  than refused, so a visitor restarts cleanly instead of hitting an error; an
  id this service never minted is still `UNKNOWN_SESSION`. Adoption always
  starts at the opening event, so it can never resurrect or leak another
  visitor's progress.
- **No real basemap.** Deliberate — see the Maps key note above. The
  deterministic schematic is shown instead.
- **Slot budget is finite.** 40 concurrent request slots (20 × 2). Well beyond
  expected judging traffic, but a large simultaneous burst would queue.
- **Not an authoritative surface.** Nothing here is evidence of managed-path
  behavior. It is `SYNTHETIC_TEST` replay of one recorded day.
