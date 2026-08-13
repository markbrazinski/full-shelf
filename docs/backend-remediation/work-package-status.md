# Backend remediation work packages

Baseline commit: `bfd1e1040824da379d69add8755682bc8eafebd6`  
Repair branch: `repair/backend-acceptance-20260813`  
Builder verdict authority: none; final acceptance requires a fresh independent audit.

| Package | Commit | Local tests | Deployed verification | Status | Blocker |
|---|---|---|---|---|---|
| WP0 — Baseline and repair map | `90dcb4a` | Read-only repository and resource inspection | Audited revisions and current resource state reconfirmed | LOCALLY VERIFIED | None |
| WP1 — Identity and ledger perimeter | — | — | — | IN PROGRESS | None |
| WP2 — Deterministic mutation boundary | — | — | — | NOT STARTED | WP1 gate |
| WP3 — Human approval and KMS | — | — | — | NOT STARTED | WP2 gate |
| WP4 — Managed Model Armor | — | — | — | NOT STARTED | WP3 gate |
| WP5 — Gemini 3.5 through ADK | — | — | — | NOT STARTED | WP4 gate |
| WP6 — Scheduler, Pub/Sub, continuity | — | — | — | NOT STARTED | WP5 gate |
| WP7 — Cloud Tasks escalation | — | — | — | NOT STARTED | WP6 gate |
| WP8 — Dynamic Spanner Graph | — | — | — | NOT STARTED | WP7 gate |
| WP9 — Event-backed SSE | — | — | — | NOT STARTED | WP8 gate |
| WP10 — Evidence, Trace, provenance | — | — | — | NOT STARTED | WP9 gate |
| WP11 — Isolated regression suite | — | — | — | NOT STARTED | WP10 gate |
| WP12 — Deployment and handoff | — | — | — | NOT STARTED | WP1–WP11 gates |

Statuses in this table are builder progress labels only: `NOT STARTED`, `IN PROGRESS`, `LOCALLY VERIFIED`, `DEPLOYED OBSERVED`, `BLOCKED`, or `FAILED`.
