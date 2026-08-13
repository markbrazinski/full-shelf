import sys
import os
import importlib.util
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

orchestrator_main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("orchestrator_main", orchestrator_main_path)
orchestrator_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrator_main)


def test_next_day_plan_generation():
    client = TestClient(orchestrator_main.app)

    mock_db = MagicMock()
    mock_snapshot = MagicMock()
    mock_snapshot.execute_sql.return_value = [("PARTIALLY_CONTAINED",)]
    mock_db.snapshot.return_value.__enter__.return_value = mock_snapshot

    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.raise_for_status.return_value = None
    mock_res.json.return_value = {
        "receipt": {"receipt_id": "RCT-NEXT-DAY-ALT", "status": "SUCCESS"},
        "idempotent_replay": False,
        "additional_mutations": 1,
    }

    with patch.object(orchestrator_main, "get_spanner_database", return_value=mock_db), \
         patch.object(orchestrator_main, "get_judge_api_key", return_value="test-key"), \
         patch.object(orchestrator_main, "PLAN_LEDGER_URL", "https://ledger.example.run.app"), \
         patch.object(orchestrator_main, "PLAN_LEDGER_AUDIENCE", "https://ledger.example.run.app"), \
         patch.object(orchestrator_main, "fetch_google_id_token", return_value="signed-workload-token"), \
         patch.object(orchestrator_main.httpx, "post", return_value=mock_res) as post:
        response = client.post(
            "/api/v1/orchestrator/next-day-plan/generate?tenant_id=east-bay-food-bank",
            headers={"X-Full-Shelf-API-Key": "test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "NEXT_DAY_DRAFT_CREATED"
        draft = data["next_day_draft"]
        assert draft["revision"] == "rev01"
        assert draft["status"] == "DRAFT_WITH_CONSTRAINTS — HUMAN APPROVAL REQUIRED"
        assert len(draft["inherited_constraints"]) == 3
        command = post.call_args.kwargs["json"]
        assert command["command_type"] == "SAVE_PLAN_REVISION"
        assert command["expected_plan_revision"] == "rev08"
        assert command["payload"]["status"] == "DRAFT_WITH_CONSTRAINTS"
