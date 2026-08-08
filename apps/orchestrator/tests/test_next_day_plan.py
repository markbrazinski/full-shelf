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

    with patch.object(orchestrator_main, "get_spanner_database", return_value=mock_db), \
         patch.object(orchestrator_main, "get_judge_api_key", return_value=""), \
         patch("httpx.post", return_value=mock_res):
        response = client.post("/api/v1/orchestrator/next-day-plan/generate?tenant_id=east-bay-food-bank")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "NEXT_DAY_DRAFT_CREATED"
        draft = data["next_day_draft"]
        assert draft["revision"] == "rev01"
        assert draft["status"] == "DRAFT_WITH_CONSTRAINTS — HUMAN APPROVAL REQUIRED"
        assert len(draft["inherited_constraints"]) == 3
