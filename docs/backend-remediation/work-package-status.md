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
| WP3 — Human approval and KMS | `3de6e36` | 88 safe tests passed; 88 collected | Revisions `orchestrator-00025-lhf` / `plan-ledger-00018-vpg`; real operator, isolated KMS/Spanner replay, ledger-runtime KMS sign, and deployed zero-mutation denials observed | DEPLOYED OBSERVED | None; successful canonical activation deliberately not used as a test |
| WP4 — Managed Model Armor | `483ee89` | 95 safe tests passed; 95 collected | Revision `orchestrator-00026-tnx`; deployed benign allow, injection block, managed sanitize logs, and zero-mutation reconciliation observed | DEPLOYED OBSERVED | None; builder testimony ready for strategy review |
| WP5 — Gemini 3.5 through ADK | `d65d1cf`, `e968bf4`, `61d4a18` | 107 safe tests passed; 107 collected | Revision `orchestrator-00029-9cx`; deployed valid extraction and ambiguous-input manual review, persisted ADK IDs, and zero-mutation reconciliation observed | DEPLOYED OBSERVED | None; builder testimony ready for strategy review |
| WP6 — Scheduler, Pub/Sub, continuity | `d199c68`, `619684d` | 114 safe tests passed; 114 collected | Revision `orchestrator-00036-xjl`; fresh Scheduler/Pub/Sub/OIDC delivery created one constrained next-day draft and idempotent duplicate retained one target receipt | DEPLOYED OBSERVED | None; builder testimony ready for strategy review |
| WP7 — Cloud Tasks escalation | `d199c68`, `619684d` | 114 safe tests passed; 114 collected | Revision `orchestrator-00036-xjl`; deployed decision created real task, managed OIDC callback committed one ledger receipt, and rejection/idempotency probes observed | DEPLOYED OBSERVED | None; builder testimony ready for strategy review |
| WP8 — Dynamic Spanner Graph | `05c2ec6` | 118 safe tests passed; 118 collected | Revision `orchestrator-00037-mpr`; canonical 96-case depth-2 and altered 51-case depth-4 managed GQL executions observed | DEPLOYED OBSERVED | None; builder testimony ready for strategy review |
| WP9 — Event-backed SSE | `1a3ace8` | 123 safe tests passed; 123 collected | Revision `orchestrator-00038-s85`; same-connection new commit and exact-cursor reconnect without duplicate observed | DEPLOYED OBSERVED | None; builder testimony ready for strategy review |
| WP10 — Evidence, Trace, provenance | `a20d9dc`, `65f247d` | 125 safe tests passed; 125 collected | Revisions `orchestrator-00040-2hc` / `plan-ledger-00020-rls`; exact evidence trace readback and fresh task→callback→ledger→receipt trace observed | DEPLOYED OBSERVED | None; builder testimony ready for strategy review |
| WP11 — Isolated regression suite | `a9ac78f` | 133 passed; 133 collected; 0 failed; 0 skipped | Audit DB `full-shelf-audit-wp6-20260813` ready; canonical receipts 17 before / 17 after | LOCALLY VERIFIED | None; builder testimony ready for independent reproduction |
| WP12 — Deployment and handoff | — | — | — | NOT STARTED | WP1–WP11 gates |

Statuses in this table are builder progress labels only: `NOT STARTED`, `IN PROGRESS`, `LOCALLY VERIFIED`, `DEPLOYED OBSERVED`, `BLOCKED`, or `FAILED`.

WP0.5 was supplied after WP1 had already been implemented. It is recorded in
the required logical order without rewriting history. WP2 work was reversibly
stashed before WP0.5 and restored only after the WP0.5 commit; no code, IAM,
data, or deployment mutation is part of the WP0.5 package.
