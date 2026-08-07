import sys
import os
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from main import app
from full_shelf_domain.kms import create_signed_approval_envelope

client = TestClient(app)


def test_get_morning_plan_preview():
    response = client.get("/api/v1/plans/preview?tenant_id=east-bay-food-bank")
    assert response.status_code == 200
    data = response.json()
    assert data["active_plan_revision"] == "v1"
    assert len(data["deliveries"]) == 5
    assert data["deliveries"][0]["order_id"] == "O201"


def test_execute_action_convert_pickup_success():
    payload = {"action": "CONVERT_TO_PARTNER_PICKUP", "order_id": "O203", "cases": 20, "plan_id": "PLAN-2026-08-07"}
    approval = create_signed_approval_envelope(
        approval_id="APP-008",
        rev_id="rev08",
        principal_id="director@fullshelf.org",
        incident_id="INC-TRUCK-01",
        plan_id="PLAN-2026-08-07",
        expected_revision="v1",
        action_type="CONVERT_TO_PARTNER_PICKUP",
        target_order_id="O203",
        target_cases=20,
        payload=payload,
        expires_at="2026-08-07T18:00:00Z",
    )

    req_body = {
        "action_id": "ACT-CONVERT-O203",
        "tenant_id": "east-bay-food-bank",
        "agent_role": "Recovery Planner",
        "action_type": "CONVERT_TO_PARTNER_PICKUP",
        "plan_id": "PLAN-2026-08-07",
        "expected_revision": "v1",
        "parameters": payload,
        "approval_envelope": approval.model_dump(),
        "idempotency_key": "IDEM-KEY-001",
    }

    response = client.post("/api/v1/actions/execute", json=req_body)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "SUCCESS"
    assert res_data["plan_revision_id"] == "v2"
    assert res_data["mutations_applied"] == 2


def test_execute_action_duplicate_idempotency_key_zero_mutations():
    """Replaying identical idempotency key yields zero additional mutations."""
    payload = {"action": "CONVERT_TO_PARTNER_PICKUP", "order_id": "O203", "cases": 20, "plan_id": "PLAN-2026-08-07"}
    req_body = {
        "action_id": "ACT-CONVERT-O203",
        "tenant_id": "east-bay-food-bank",
        "agent_role": "Recovery Planner",
        "action_type": "CONVERT_TO_PARTNER_PICKUP",
        "plan_id": "PLAN-2026-08-07",
        "expected_revision": "v2",
        "parameters": payload,
        "idempotency_key": "IDEM-KEY-001",  # Same idempotency key as prior test
    }

    response = client.post("/api/v1/actions/execute", json=req_body)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "SUCCESS"
    assert res_data["mutations_applied"] == 0
    assert "Duplicate idempotency key" in res_data["message"]


def test_trigger_recall_96_unique_cases_and_terminal_state():
    response = client.post("/api/v1/incidents/recall", json={"lot_id": "LOT-RECALL-88", "hazard": "E. coli O157:H7"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "RECALL_BARRIER_ACTIVATED"
    assert data["plan_status"] == "INVALIDATED_RECALL"
    assert data["reconciliation"]["total_unique_physical_cases"] == 96
    assert data["reconciliation"]["sub_distributed_unconfirmed_cases"] == 8
    assert data["reconciliation"]["terminal_status"] == "PARTIALLY_CONTAINED_AWAITING_RECOVERY"


def test_get_system_evidence():
    response = client.get("/api/v1/evidence/system")
    assert response.status_code == 200
    data = response.json()
    assert data["gcp_project_id"] == "preflight-hackathon"
    assert data["spanner_database"] == "full-shelf-main"
