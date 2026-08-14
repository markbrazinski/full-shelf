import importlib.util
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from full_shelf_domain.identity import VerifiedGoogleIdentity


main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("orchestrator_callback_main", main_path)
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)

CALLER = VerifiedGoogleIdentity(
    subject="105774551577568412756",
    email="full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com",
    audience="https://orchestrator.example.run.app",
    issuer="https://accounts.google.com",
    expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
)


def test_task_callback_rejects_unauthenticated_before_ledger():
    client = TestClient(main.app)
    with patch.object(
        main, "_verify_managed_callback", side_effect=main.HTTPException(401, "required")
    ), patch.object(main, "execute_ledger_command") as ledger:
        response = client.post(
            "/api/v1/incidents/site01-deadline",
            headers={
                "X-CloudTasks-TaskName": "task-forged",
                "X-CloudTasks-QueueName": "full-shelf-deadlines",
            },
            json={"incident_id": "INC-RECALL-01", "site_id": "SITE-01",
                  "task_decision_id": "task-forged"},
        )
    assert response.status_code == 401
    ledger.assert_not_called()


def test_task_callback_uses_verified_identity_and_cannot_bypass_ledger():
    client = TestClient(main.app)
    ledger_result = {
        "receipt": {"receipt_id": "RCT-TASK-ALT", "status": "SUCCESS"},
        "idempotent_replay": False,
    }
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "execute_ledger_command", return_value=ledger_result
    ) as ledger:
        response = client.post(
            "/api/v1/incidents/site01-deadline",
            headers={
                "Authorization": "Bearer signed",
                "X-CloudTasks-TaskName": "task-alt",
                "X-CloudTasks-QueueName": "full-shelf-deadlines",
                "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
            },
            json={"incident_id": "INC-RECALL-01", "site_id": "SITE-01",
                  "task_decision_id": "task-alt",
                  "correlation_trace_id": "0123456789abcdef0123456789abcdef"},
        )
    assert response.status_code == 200
    command = ledger.call_args.kwargs
    assert command["command_type"] == "RECORD_ACKNOWLEDGMENT_HOLD"
    assert command["idempotency_key"].startswith("cloud-task:")
    assert command["payload"]["delivery_subject"] == CALLER.subject
    assert command["payload"]["delivery_audience"] == CALLER.audience
    assert command["trace_id"] == "0123456789abcdef0123456789abcdef"
    assert "correlation_trace_id" not in command["payload"]


def test_task_creation_is_explicitly_audience_bound_without_local_fallback():
    client = MagicMock()
    client.queue_path.return_value = "projects/p/locations/l/queues/q"
    client.task_path.return_value = "projects/p/locations/l/queues/q/tasks/t"
    client.create_task.return_value = MagicMock(name="created")
    client.create_task.return_value.name = "projects/p/locations/l/queues/q/tasks/t"
    with patch("google.cloud.tasks_v2.CloudTasksClient", return_value=client):
        result = main.schedule_site01_deadline_task(
            "INC-RECALL-01",
            task_id="t",
            orchestrator_url="https://orchestrator.example.run.app",
            oidc_audience="https://orchestrator.example.run.app",
            delivery_service_account="delivery@example.iam.gserviceaccount.com",
            trace_id="0123456789abcdef0123456789abcdef",
        )
    task = client.create_task.call_args.kwargs["request"]["task"]
    assert result["status"] == "SCHEDULED"
    assert task["http_request"]["oidc_token"] == {
        "service_account_email": "delivery@example.iam.gserviceaccount.com",
        "audience": "https://orchestrator.example.run.app",
    }
    assert task["http_request"]["headers"]["traceparent"].startswith(
        "00-0123456789abcdef0123456789abcdef-"
    )
    assert result["correlation_trace_id"] == "0123456789abcdef0123456789abcdef"
