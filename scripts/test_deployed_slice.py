import subprocess
import json
import httpx
import sys
import os

# Deployed Cloud Run URLs
ORCHESTRATOR_URL = "https://full-shelf-orchestrator-620464070103.us-central1.run.app"
PLAN_LEDGER_URL = "https://full-shelf-plan-ledger-620464070103.us-central1.run.app"

sys.path.insert(0, os.path.abspath("packages/domain"))
from full_shelf_domain.kms import create_signed_approval_envelope


def get_oidc_identity_token() -> str:
    """Fetches Google Cloud OIDC identity token for service invocation."""
    cmd = "CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.11 gcloud auth print-identity-token"
    token = subprocess.check_output(cmd, shell=True).decode().strip()
    return token


def main():
    print("=== 1. Testing Health Endpoints on Cloud Run ===", flush=True)
    res_orch_health = httpx.get(f"{ORCHESTRATOR_URL}/")
    print(f"Orchestrator Health ({res_orch_health.status_code}): {res_orch_health.json()}", flush=True)
    assert res_orch_health.status_code == 200

    print("\n=== 2. Obtaining OIDC Identity Token for Plan Ledger ===", flush=True)
    token = get_oidc_identity_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print(f"OIDC Token fetched successfully (Length: {len(token)})", flush=True)

    print("\n=== 3. Testing Plan Ledger Preview via Authenticated OIDC Call ===", flush=True)
    res_preview = httpx.get(f"{PLAN_LEDGER_URL}/api/v1/plans/preview", headers=headers)
    print(f"Plan Ledger Preview ({res_preview.status_code}): {res_preview.json()}", flush=True)
    assert res_preview.status_code == 200
    assert res_preview.json()["active_plan_revision"] == "rev07"

    print("\n=== 4. Executing Real rev08 Proposal & KMS Approval on Deployed Plan Ledger ===", flush=True)
    approval = create_signed_approval_envelope(
        approval_id="APP-008",
        rev_id="rev08",
        principal_id="operations-director@fullshelf.org",
        incident_id="INC-TRUCK-01",
        plan_id="PLAN-2026-08-07",
        source_revision="rev07",
        proposed_revision="rev08",
        reroute_order_id="O202",
        reroute_cases=22,
        reroute_target_vehicle="TRUCK-02",
        pickup_order_id="O203",
        pickup_cases=20,
        expires_at="2026-08-07T18:00:00Z",
    )

    req_body = {
        "action_id": "ACT-DEPLOYED-REV08",
        "tenant_id": "east-bay-food-bank",
        "agent_role": "Recovery Planner",
        "action_type": "APPLY_REPAIR_PLAN_REV08",
        "plan_id": "PLAN-2026-08-07",
        "expected_revision": "rev07",
        "parameters": {"action": "APPLY_REV08"},
        "approval_envelope": approval.model_dump(),
        "idempotency_key": "IDEM-KEY-DEPLOYED-001",
    }

    res_exec = httpx.post(f"{PLAN_LEDGER_URL}/api/v1/actions/execute", headers=headers, json=req_body)
    print(f"Action Execution Response ({res_exec.status_code}):\n{json.dumps(res_exec.json(), indent=2)}", flush=True)
    assert res_exec.status_code == 200
    exec_data = res_exec.json()
    assert exec_data["status"] == "SUCCESS"
    assert exec_data["plan_revision_id"] == "rev08"
    assert exec_data["mutations_applied"] == 2

    print("\n=== 5. Testing Idempotent Replay on Deployed Plan Ledger ===", flush=True)
    res_replay = httpx.post(f"{PLAN_LEDGER_URL}/api/v1/actions/execute", headers=headers, json=req_body)
    print(f"Idempotent Replay Response ({res_replay.status_code}):\n{json.dumps(res_replay.json(), indent=2)}", flush=True)
    assert res_replay.status_code == 200
    replay_data = res_replay.json()
    assert replay_data["status"] == "SUCCESS"
    assert replay_data["mutations_applied"] == 0
    assert "Duplicate idempotency key" in replay_data["message"]

    print("\n=== 6. Testing Unauthenticated Request Denial to Plan Ledger ===", flush=True)
    unauth_res = httpx.get(f"{PLAN_LEDGER_URL}/api/v1/plans/preview")
    print(f"Unauthenticated Call Response ({unauth_res.status_code})", flush=True)
    assert unauth_res.status_code == 401 or unauth_res.status_code == 403

    print("\n✅ Gate 1 Deployed Slice End-to-End Verification Passed Cleanly!", flush=True)


if __name__ == "__main__":
    main()
