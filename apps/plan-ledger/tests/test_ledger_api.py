import sys
import os
from fastapi.testclient import TestClient

import importlib.util

ledger_main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("plan_ledger_main", ledger_main_path)
ledger_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger_main)

from full_shelf_domain.kms import create_signed_approval_envelope

client = TestClient(ledger_main.app)


def test_get_morning_plan_preview():
    response = client.get("/api/v1/plans/preview?tenant_id=east-bay-food-bank")
    assert response.status_code == 200
    data = response.json()
    assert data["active_plan_revision"] in ["rev07", "rev08"]
    assert len(data["deliveries"]) == 5
    assert data["deliveries"][0]["order_id"] == "O201"


def test_execute_action_rev08_approved_plan_diff_success():
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
        use_live_kms=True,
    )

    req_body = {
        "action_id": "ACT-APPLY-REV08-001",
        "tenant_id": "east-bay-food-bank",
        "agent_role": "Recovery Planner",
        "action_type": "APPLY_REPAIR_PLAN_REV08",
        "plan_id": "PLAN-2026-08-07",
        "expected_revision": "rev07",
        "parameters": {"action": "APPLY_REV08"},
        "approval_envelope": approval.model_dump(),
        "idempotency_key": "IDEM-KEY-REV08-001",
    }

    response = client.post("/api/v1/actions/execute", json=req_body)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "SUCCESS"
    assert res_data["plan_revision_id"] == "rev08"
    assert res_data["mutations_applied"] == 2


def test_execute_action_duplicate_idempotency_key_zero_mutations():
    """Replaying identical action_id / idempotency key yields zero additional mutations."""
    req_body = {
        "action_id": "ACT-APPLY-REV08-001",
        "tenant_id": "east-bay-food-bank",
        "agent_role": "Recovery Planner",
        "action_type": "APPLY_REPAIR_PLAN_REV08",
        "plan_id": "PLAN-2026-08-07",
        "expected_revision": "rev08",
        "parameters": {"action": "APPLY_REV08"},
        "idempotency_key": "IDEM-KEY-REV08-001",
    }

    response = client.post("/api/v1/actions/execute", json=req_body)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] in ["SUCCESS", "DENIED"]
    assert res_data["mutations_applied"] == 0


def test_trigger_recall_96_unique_cases_and_terminal_state():
    response = client.post("/api/v1/incidents/recall", json={"lot_id": "LTC-4471", "hazard": "E. coli O157:H7"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "RECALL_BARRIER_ACTIVATED"
    assert data["plan_status"] == "INVALIDATED_RECALL"
    assert data["reconciliation"]["total_unique_physical_cases"] == 96
    assert data["reconciliation"]["sub_distributed_unconfirmed_cases"] == 8
    assert data["reconciliation"]["terminal_status"] == "PARTIALLY_CONTAINED"


def test_get_system_evidence():
    response = client.get("/api/v1/evidence/system")
    assert response.status_code == 200
    data = response.json()
    assert data["gcp_project_id"] == "preflight-hackathon"
    assert data["spanner_database"] == "full-shelf-main"
