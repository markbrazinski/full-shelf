# Backend remediation work packages

Baseline commit: `bfd1e1040824da379d69add8755682bc8eafebd6`  
Repair branch: `repair/backend-acceptance-20260813`  
Builder verdict authority: none; final acceptance requires a fresh independent audit.

| Package | Commit | Local tests | Deployed verification | Status | Blocker |
|---|---|---|---|---|---|
| WP0 — Baseline and repair map | `90dcb4a` | Read-only repository and resource inspection | Audited revisions and current resource state reconfirmed | LOCALLY VERIFIED | None |
| WP0.5 — Canonical agent constitution | `3994a87` | Instruction inventory and contradiction review | Not applicable; documentation-only package | STRUCTURALLY_VERIFIED | None |
| WP1 — Identity and ledger perimeter | `ea462c0`, `833c478`, `4763392` | 28 targeted tests passed | Revisions `orchestrator-00023-frt` / `plan-ledger-00016-x4j`; all acceptance outcomes observed | DEPLOYED OBSERVED | None |
| WP2 — Deterministic mutation boundary | `22d86f9` | 69 safe tests passed; 87 collected | Revisions `orchestrator-00024-kwm` / `plan-ledger-00017-7mh`; isolated replay and deployed zero-mutation tenant denial observed | DEPLOYED OBSERVED | None; orchestrator URL anomaly carried to end-to-end replay |
| WP3 — Human approval and KMS | Working tree | 52 focused tests passed | Real operator verified; ledger-only KMS IAM applied | IN PROGRESS | Isolated managed replay and deployment pending |
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

WP0.5 was supplied after WP1 had already been implemented. It is recorded in
the required logical order without rewriting history. WP2 work was reversibly
stashed before WP0.5 and restored only after the WP0.5 commit; no code, IAM,
data, or deployment mutation is part of the WP0.5 package.
