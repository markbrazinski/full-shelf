# Full Shelf — Release Audit

**Date:** 2026-08-28
**Branch:** `main`
**Skill:** `repo-release-readme` v1.1

## 1. Verdict

**PASS WITH LIMITATIONS.** The repository is safe to make public. The offline
deterministic path is fully verified from a clean virtual environment. Live
Google Cloud integration (Gemini, Model Armor, KMS, Spanner) is **not** verified
here and is documented as unverified rather than claimed.

## 2. Repository mode

**Local-only**, by deliberate design. There is no publicly reachable hosted URL
to document, so the README carries no `Run it` section; `Run locally` is the
complete getting-started path and requires no cloud credentials.

## 3. Files changed

| File | Change |
|---|---|
| `README.md` | Rewritten into canonical product-first order (see §8) |
| `LICENSE` | **Added** — Apache-2.0, © 2026 Mark Brazinski (user-selected) |
| `RELEASE_AUDIT.md` | **Added** — this report |
| `apps/orchestrator/requirements.txt` | **Added `pytest-asyncio>=1.4.0`** — real undeclared dependency (see §12) |
| `apps/plan-ledger/requirements.txt` | Same addition |
| `.gitignore` | Added `test-results/`, `playwright-report/` |
| `docs/images/*.png` | **Added** — three README proof images copied from the verified golden run |

## 4. Files removed

None deleted. Six internal builder reports were **moved**, not removed, via
`git mv` into `docs/build-reports/`:

`CONTRACT_V2_CONFORMANCE.md`, `DECISION_CHECKPOINT.md`, `DELIVERY_CANDIDATE.md`,
`GOLDEN_PATH_REPAIR_COMPLETE.md`, `IMPLEMENTATION_STATUS.md`, `REPAIR_STATUS.md`

Rationale: `AGENTS.md` classifies builder reports as non-authoritative testimony
worth retaining, but they are internal handoffs that should not be the first
thing a stranger sees at repository root. Two of the six are explicitly marked
"SUPERSEDED AND REVERTED — DO NOT RELY ON THIS DOCUMENT"; that self-correction is
itself worth preserving as evidence of honest process. Root now holds only
`README.md`, `LICENSE`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `RELEASE_AUDIT.md`.

## 5. Secret scan

**PASS.** `git grep` across all 356 tracked files for Google API keys (`AIza…`),
OpenAI keys (`sk-…`), GitHub tokens (`ghp_…`), Slack tokens (`xox…`), and PEM
private-key headers returned **zero matches**.

`.env.example` contains no credentials. It does contain non-secret Google Cloud
resource identifiers (project `preflight-hackathon`, project number
`620464070103`, service-account emails, Cloud Run URLs, a KMS key path, and SA
numeric subjects). These are **resource names, not credentials** — they grant no
access without IAM authorization. Retained deliberately: they document the real
deployed topology, and the ledger independently authenticates every caller.

`.gitignore` correctly excludes `.env`, `*.pem`, `*.key`.

No real credential was found in Git history; no history rewrite was performed.

## 6. License

Previously **absent** — a public repository with no usage rights granted. Now
`LICENSE`, Apache-2.0 (202 lines, unmodified upstream text, copyright fields
filled). GitHub will auto-detect it. The README links it. Apache-2.0 was chosen
by the user, matching the Covenant repository's convention and providing the
explicit patent grant appropriate to a Google-platform submission.

## 7. Image assets added

All three are real captures from the verified end-to-end run, not mockups.

| Path | Source | Shows |
|---|---|---|
| `docs/images/repair-proposal.png` | `golden/03-repair-proposal.png` | Live Google Maps dispatch, truck manifests, the `36 + 22 = 58 / 60` capacity arithmetic, and the un-pressed **Approve update** gate |
| `docs/images/custody-reconciliation.png` | `golden/06-custody.png` | Spanner Graph custody traversal, `24+22+20+10+8+12 = 96`, eight cases flagged `UNCONFIRMED` at Site 01 |
| `docs/images/governed-refusal.png` | `golden/08-recovery-committed-refusal.png` | 40 safe replacements committed, truthful 20-case shortfall, closure **refused** at `PARTIALLY_CONTAINED` |

Every image carries the `DETERMINISTIC TEST MODE · SYNTHETIC_TEST` banner, so no
screenshot can be mistaken for live operational data. No credentials, tokens, or
private URLs are visible. The first two are embedded at the top of the README.

## 8. README section order — before → after

**Before (6 sections):**

```
Title → Architecture Highlights → Local Setup & Development Workflow →
Prerequisites → Quickstart → Key Demo Scenario Verification
```

**After (10 sections):**

```
Title + thesis paragraph → 2 proof images → How it works (4 stages) →
Run locally (Prerequisites / Install / Start / Health checks / Shutdown) →
Technologies and dependencies → Verification → Repository structure →
Sample outputs → License → Honest boundaries
```

The lists are not identical; Phase 5 was performed. What changed materially:

- The old README had **no product thesis** — it opened by naming a hackathon
  track, not the problem. The new opening paragraph states the triggering event,
  the user, what the product does, and what is durable.
- The old README had **no images**, despite 58 committed screenshots from a
  passing verified run already sitting in the repository.
- "Architecture Highlights" listed *components*; it is replaced by "How it works"
  using product verbs (Detect and propose → Approve under binding → Trace custody
  → Recover, and refuse the rest) and demoted technology detail to its own
  section with a stated runtime responsibility per entry.
- The old README claimed `apps/web` "has no application entry point yet" and that
  "the React client is built separately." **This was stale and false** — there is
  a complete React client with 58 passing Playwright tests. The most important
  correction in this pass.
- Added `Verification`, `Repository structure`, `Sample outputs`, `License`, and
  `Honest boundaries`, none of which existed.

## 9. Getting-started commands — every one was run

| Command | Run? | Result |
|---|---|---|
| `python3 -m venv .venv` | ✅ | Verified in a throwaway venv |
| `pip install -e packages/domain -e packages/observability -r …` | ✅ | Exit 0 from clean venv |
| `npm --prefix apps/web install` | ✅ | Completed |
| `pytest -q packages/domain/tests packages/contracts/tests tools/replay` | ✅ | `540 passed` — observed count in README |
| `.venv/bin/python tools/replay/runtime_server.py` | ✅ | Banner in README is copied observed stdout |
| `npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5173` | ✅ | Vite output in README is observed |
| `curl -s …/api/v1/replay/events \| head -c 150` | ✅ | Output in README is the real response |
| `curl -s http://127.0.0.1:5173 \| grep -o "<title>…"` | ✅ | Observed |
| `npm --prefix apps/web test` | ✅ | `58 passed (6.4m)` |
| `npm --prefix apps/web run typecheck` | ✅ | Clean |
| `npm --prefix apps/web run build` | ✅ | `✓ built in 402ms` |

No command appears in the README that was not executed in exactly its documented
form. All expected outputs are transcribed from observed runs, not idealized.

## 10. Links and image paths

**PASS.** All 7 relative README targets resolve on disk (3 images, 3 directories,
`LICENSE`, and the event-contract document). Verified programmatically.

## 11. Clean-clone result

**PARTIAL — dependency install and full test suite verified in an isolated fresh
virtual environment**, which is what surfaced the finding in §12. A literal
`git clone` into a new directory was not performed, because the working tree is
the authoritative copy and no push was authorized. The install path was exercised
from a genuinely empty interpreter, so the dependency closure is proven.

## 12. Tests run and exact results

| Suite | Command scope | Result |
|---|---|---|
| Domain + contracts + replay | root-relative | **540 passed** in 5.04s |
| Playwright e2e | against real replay runtime on 8788 | **58 passed** in 6.4m |
| TypeScript | `tsc --noEmit` | clean |
| Production build | `vite build` | `✓ built in 402ms` |

### Finding: undeclared `pytest-asyncio` (fixed)

A clean-venv install reproduced a failure the developer machine hid:

```
FAILED packages/domain/tests/test_partner_evidence.py::
  test_real_adk_runner_persists_only_emitted_identifiers
async def functions are not natively supported.
```

`pytest-asyncio` was installed in the local `.venv` but declared in **no**
requirements file, so any fresh clone would silently fail that test. Added
`pytest-asyncio>=1.4.0` to both service requirements files. Re-verified: the
fresh venv now reports **540 passed**.

### Finding: subdirectory pytest invocation bypasses the safety conftest

The previous README documented `python -m pytest packages/domain/tests`. Invoked
that way, pytest resolves its rootdir to `packages/domain` and **never loads the
root `conftest.py`**, which is the guard that forces every test onto a named
isolated audit database. The symptom was a failing
`test_wp11_isolation.py::test_full_suite_is_forced_onto_named_audit_database`;
the cause was the documented command itself. The README now documents the
root-relative invocation and explains why it matters. No production code changed.

## 13. Hosted smoke test

**N/A.** No publicly reachable deployment is claimed. The `.env.example` Cloud
Run URLs reference a private project requiring IAM authorization; the README does
not present them as an evaluation path.

## 14. Unresolved blockers

None blocking public release.

Non-blocking, recorded: `npm audit` reports 2 advisories (1 moderate, 1 high) in
`esbuild`/`vite`, both **devDependencies affecting only the local dev server**,
not shipped output. The remedy is `vite@8` — a breaking major upgrade the skill's
change limits forbid without authorization. Not exploitable in a static build.

## 15. User input still required

- Confirm the repository name at `github.com/markbrazinski/full-shelf` before
  making it public; the README clone URL matches the configured `origin`.
- Optional: a demo video link. The README has no `Demo` section because no video
  or hosted link exists — an empty section of dead links would be worse.

## 16. Safe to make public

Yes. No secrets in the tree or history, a detectable license, all demonstrated
data explicitly synthetic and labelled as such in-product, and every claim in the
README backed by a command that was actually run.

## 17. Exact final verification commands

```bash
# offline suites — no credentials required
PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python -m pytest -q packages/domain/tests packages/contracts/tests tools/replay
# expect: 540 passed

# end-to-end, with the replay runtime running on 127.0.0.1:8788
.venv/bin/python tools/replay/runtime_server.py &
VITE_ORCHESTRATOR_URL=http://127.0.0.1:8788 npm --prefix apps/web test
# expect: 58 passed

npm --prefix apps/web run typecheck && npm --prefix apps/web run build
# expect: clean, then ✓ built
```

> **SAFE TO MAKE PUBLIC: YES**
