import httpx
import json
import subprocess
import time

ORCHESTRATOR_URL = "https://full-shelf-orchestrator-620464070103.us-central1.run.app"
JUDGE_KEY = "fs-judge-key-2026"


def main():
    print("=" * 60)
    print("      FULL SHELF RECALL HERO LOOP (PART B) EVIDENCE PROOF      ")
    print("=" * 60)

    headers = {"X-Full-Shelf-API-Key": JUDGE_KEY}

    # 1. Trigger Recall Hero Loop on Deployed Orchestrator
    print("\n--- 1. Triggering Recall Hero Loop Endpoint ---")
    res = httpx.post(f"{ORCHESTRATOR_URL}/api/v1/orchestrator/recall/trigger", headers=headers, timeout=20.0)
    print(f"Recall Trigger Response Status: {res.status_code}")
    data = res.json()
    print(json.dumps(data, indent=2))

    trace_id = data.get("cloud_trace_id")
    print(f"\nReal 32-Character Trace ID across Pub/Sub, ADK, and Spanner: {trace_id}")

    # Assertions
    assert data.get("pubsub_receipt", {}).get("status") == "PUBLISHED"
    assert data.get("model_armor_screening", {}).get("status") == "APPROVED"
    assert data.get("gemini_entity_extraction", {}).get("lot_id") == "LTC-4471"
    assert data.get("spanner_incident", {}).get("incident_id") == "INC-RECALL-01"
    assert data.get("terminal_state") == "PARTIALLY_CONTAINED"

    # 2. Query Incident Status from Spanner
    print("\n--- 2. Querying Spanner Incident Status ---")
    res_status = httpx.get(f"{ORCHESTRATOR_URL}/api/v1/orchestrator/recall/incident-status?incident_id=INC-RECALL-01")
    print(f"Incident Status Status: {res_status.status_code}")
    status_data = res_status.json()
    print(json.dumps(status_data, indent=2))

    assert status_data.get("terminal_state") == "PARTIALLY_CONTAINED"

    print("\n" + "=" * 60)
    print("✅ PART B RECALL HERO LOOP BACKEND VERIFICATION COMPLETE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
