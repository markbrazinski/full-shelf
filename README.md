# Full Shelf — Food-Bank Fulfillment Control Plane

**Full Shelf** is a production-minded food-bank fulfillment control plane built for Google's All Things Agentic Hackathon (Fortified Enterprise Fleet track).

## Architecture Highlights
- **ADK / Gemini Orchestrator (`apps/orchestrator`)**: Read-only agent fleet reasoning over operational state; invokes `plan-ledger` via policy tools.
- **Deterministic Plan Ledger (`apps/plan-ledger`)**: Authoritative, policy-checked mutation engine with Spanner R/W, KMS signature verification, and Model Armor input filtering.
- **Cloud Spanner & Spanner Graph**: Relational operational state and graph custody traversal across warehouse, trucks, staging, agencies, and sub-distributed sites (96 physical cases).
- **React Frontend API Boundary (`apps/web`)**: Strongly typed TypeScript client boundary, routing shell, and environment contract reserved for UI integration.

## Local Setup & Development Workflow

### Prerequisites
- Python 3.11+
- Node.js 18+ / pnpm or npm
- Google Cloud SDK (`gcloud`) configured with project `preflight-hackathon`

### Quickstart
1. Install Python shared domain and dependencies:
   ```bash
   pip install -e packages/domain
   pip install -r apps/plan-ledger/requirements.txt
   pip install -r apps/orchestrator/requirements.txt
   ```
2. Run Unit & Contract Tests:
   ```bash
   python -m pytest packages/domain/tests
   ```
3. Run Local Dev Stack:
   ```bash
   ./scripts/dev.sh
   ```

## Key Demo Scenario Verification
The test suite validates:
1. **Capacity infeasibility check**: Proves $36 + 22 + 20 = 78 > 60$ case truck capacity limit.
2. **KMS approval binding**: Cryptographically validates approval `rev08` envelope binding action payload hash and plan revision.
3. **Unauthorized mutation denial**: Guarantees zero DB mutations when policies fail or plan revision is stale.
4. **Idempotent replay**: Replaying identical action requests yields zero additional mutations.
5. **Recall graph reconciliation**: Reconciles 96 unique cases across custody nodes without double counting.
6. **Tenant isolation**: Enforces tenant-scoped query and mutation boundary.
7. **Truthful unresolved terminal state**: Evaluates to `PARTIALLY_CONTAINED_AWAITING_RECOVERY` while downstream acknowledgments remain pending.
