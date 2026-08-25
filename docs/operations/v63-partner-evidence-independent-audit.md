# V6.3 partner evidence independent-audit commission

Audit only this frozen implementation commit:

`055ef231cd29dd289c02edd151c832fa162c4266`

Its required base and merge base are:

`9e9d7fd8a882b751999e317ee607c5d76e5900e4`

The builder did not merge, push, deploy, or access canonical cloud state. An
independent auditor must reproduce evidence from a clean checkout and must not
accept the builder handoff, screenshots, configuration, or green tests as
managed-path proof.

## Safety gate

Before running anything, require all of the following:

1. `git rev-parse HEAD` equals the frozen implementation commit.
2. `git merge-base HEAD 9e9d7fd8a882b751999e317ee607c5d76e5900e4`
   equals that base.
3. The checkout is clean.
4. Every Spanner target is an ephemeral official emulator database. Refuse
   `full-shelf-main`, any configured canonical database, and every cloud
   endpoint.
5. No command merges, pushes, deploys, changes IAM, or reads canonical state.

## Local structural and regression evidence

Run the constitution suite exactly as specified in `AGENTS.md`, then run:

```bash
PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python -m pytest --collect-only -q \
  packages/domain/tests apps/orchestrator/tests apps/plan-ledger/tests

PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python -m pytest -q \
  packages/contracts/tests \
  packages/domain/tests/test_partner_evidence.py \
  packages/domain/tests/test_partner_evidence_ledger.py \
  apps/orchestrator/tests/test_partner_evidence_ingress.py \
  apps/orchestrator/tests/test_bounded_projection.py \
  apps/orchestrator/tests/test_projection_contract_schema.py \
  apps/orchestrator/tests/test_route_authentication.py \
  tools/replay/test_replay_contract.py

PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src:apps/plan-ledger/src \
  .venv/bin/python -m pytest -q

git diff --check
```

Require strict work-item validation, the constant event type, exact callback
classification and dependency, five-agent preservation, single mutation
authority, approval binding, lifecycle and tenant isolation, canonical
quantities, main/proof isolation, rollback on the second update, stable replay,
permanent conflict, and cursor-only SSE assertions to pass.

## Official Spanner emulator

Start the official Google Spanner emulator on loopback. Create two fresh,
noncanonical databases in a disposable emulator instance:

- `full-schema-audit`, built from the frozen commit's complete
  `infra/spanner/schema.sql`;
- `migrated-schema-audit`, built from the base commit's complete schema and
  then upgraded with `infra/spanner/migrations/007_v63_partner_evidence.sql`.

Require every DDL statement to complete successfully. Then run the checked-in
verifier with unique tenant names:

```bash
SPANNER_EMULATOR_HOST=127.0.0.1:9010 \
PYTHONPATH=packages/domain:packages/observability \
  .venv/bin/python scripts/verify_v63_partner_evidence_emulator.py \
  --instance=full-shelf-v63-audit \
  --database=full-schema-audit \
  --tenant=audit-v63-full

SPANNER_EMULATOR_HOST=127.0.0.1:9010 \
PYTHONPATH=packages/domain:packages/observability \
  .venv/bin/python scripts/verify_v63_partner_evidence_emulator.py \
  --instance=full-shelf-v63-audit \
  --database=migrated-schema-audit \
  --tenant=audit-v63-migrated
```

The verifier must refuse a missing emulator host and the canonical database
name. For each database require:

- vague: `DENIED`, 88 confirmed cases, work item `OPEN`, zero domain
  mutations, one evidence mutation;
- identical replay: original receipt, original accounting, zero new writes;
- complete: `SUCCESS`, 96 confirmed cases, the exact stored work item
  `COMPLETED`, two domain mutations, one evidence mutation;
- exactly two evidence rows and exactly two linked receipts total;
- non-null identifiers emitted by the real ADK Runner event loop and no
  invented run identifier.

Independently inject a failure into the second domain update and require the
custody update, evidence insert, and receipt insert all to roll back.

## Replay and frontend

Generate fixtures from the production projection handler, start the replay
server on loopback, and use ports not occupied by another checkout:

```bash
PYTHONPATH=packages/domain:packages/observability:apps/orchestrator/src \
  .venv/bin/python tools/replay/generate_fixtures.py

cd apps/web
npm ci
npm run typecheck
npm run build

FULL_SHELF_WEB_PORT=5190 \
VITE_ORCHESTRATOR_URL=http://127.0.0.1:8790 \
  npm test
```

Run `tools/replay/server.py` separately with
`FULL_SHELF_REPLAY_PORT=8790` and
`FULL_SHELF_WEB_ORIGIN=http://127.0.0.1:5190`. Require all configured
Playwright cases at 1600×900. Confirm the canonical twelve-beat timeline stays
88/96 and `PARTIALLY_CONTAINED`, while the isolated vague and complete views
show the source, Model Armor result, Partner Operations interpretation,
claim-by-claim anchors, deterministic decision, receipt, separate mutation
counts, custody transition, work-item transition, and real ADK identifiers.
No clarification-send, fact-approval, or delivery control may appear.

## Acceptance classification

Local tests and official-emulator results may support `MEASURED` and
`STRUCTURALLY_VERIFIED` conclusions only. Managed Model Armor, live Gemini,
Google-signed callback identity, Cloud Run, IAM, managed delivery, Cloud Trace,
and production Spanner remain `NOT_PROVEN` unless the project authority later
authorizes a separate managed-path audit. Do not broaden this commission into
deployment or canonical-state access.

Final acceptance must be issued by an auditor other than the builder and must
name the frozen implementation commit in its report.
