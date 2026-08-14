import importlib.util
import os
import base64
import json
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


def _pubsub_envelope(event, message_id="scheduler-message-1"):
    return {
        "message": {
            "messageId": message_id,
            "publishTime": "2026-08-14T12:30:00Z",
            "data": base64.b64encode(json.dumps(event).encode()).decode(),
        }
    }


def _minimal_operating_plan():
    return {
        "tenant_name": "Audit day", "plan_id": "PLAN-AUDIT",
        "revision": "rev07", "status": "ACTIVE",
        "lots": [{"lot_id": "LOT-A", "code": "LOT-A", "produce_type": "Greens",
                  "hazard_status": "CLEAR_SAFE", "total_cases": 4}],
        "vehicles": [{"vehicle_id": "VEHICLE-A", "name": "Vehicle A",
                      "max_capacity_cases": 10, "current_load_cases": 4,
                      "is_operational": True}],
        "orders": [{"order_id": "ORDER-A", "destination_agency_id": "AG-A",
                    "destination_agency_name": "Agency A", "cases": 4,
                    "lot_id": "LOT-A", "assigned_vehicle_id": "VEHICLE-A",
                    "status": "SCHEDULED"}],
        "custody_nodes": [
            {"node_id": "NODE-WH", "node_type": "WAREHOUSE", "name": "Warehouse",
             "on_hand_cases": 2},
            {"node_id": "NODE-AG", "node_type": "AGENCY", "name": "Agency",
             "on_hand_cases": 2},
        ],
        "custody_edges": [{"edge_id": "EDGE-A", "source_node_id": "NODE-WH",
                           "target_node_id": "NODE-AG", "lot_id": "LOT-A",
                           "case_count": 2, "is_sub_distribution": False}],
    }


def test_pubsub_daily_delivery_requires_google_identity_before_plan_logic():
    client = TestClient(main.app)
    event = {"event_type": "PLAN_DAY_REQUESTED", "tenant_id": "east-bay-food-bank",
             "operating_plan": _minimal_operating_plan()}
    with patch.object(
        main, "_verify_managed_callback", side_effect=main.HTTPException(401, "required")
    ), patch.object(main, "_generate_daily_morning_plan") as generate:
        response = client.post("/api/v1/orchestrator/pubsub/push", json=_pubsub_envelope(event))

    assert response.status_code == 401
    generate.assert_not_called()


def test_authenticated_duplicate_daily_deliveries_return_stable_2xx_result():
    client = TestClient(main.app)
    event = {"event_type": "PLAN_DAY_REQUESTED", "tenant_id": "east-bay-food-bank",
             "operating_plan": _minimal_operating_plan()}
    results = [
        {"status": "DAILY_PLAN_GENERATED_REV07", "idempotent_replay": False},
        {"status": "DAILY_PLAN_EXISTS_IDEMPOTENT", "idempotent_replay": True},
    ]
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_generate_daily_morning_plan", side_effect=results
    ) as generate:
        first = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event),
        )
        duplicate = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event),
        )

    assert first.status_code == duplicate.status_code == 200
    assert first.json()["daily_plan_result"]["status"] == "DAILY_PLAN_GENERATED_REV07"
    assert duplicate.json()["daily_plan_result"]["idempotent_replay"] is True
    assert generate.call_count == 2
    assert generate.call_args_list[0].kwargs["source_event_id"] == "scheduler-message-1"


def test_authenticated_duplicate_next_day_deliveries_return_2xx():
    client = TestClient(main.app)
    event = {"event_type": "PLAN_NEXT_DAY_REQUESTED", "tenant_id": "east-bay-food-bank"}
    stable = {
        "status": "NEXT_DAY_DRAFT_CREATED", "idempotent_replay": True,
        "ledger_receipt": {"receipt_id": "RCT-STABLE", "status": "SUCCESS"},
    }
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_generate_next_day_plan", return_value=stable
    ) as generate:
        first = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event, "next-day-message-1"),
        )
        duplicate = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event, "next-day-message-1"),
        )

    assert first.status_code == duplicate.status_code == 200
    assert first.json()["next_day_plan_result"]["ledger_receipt"]["receipt_id"] == "RCT-STABLE"
    assert generate.call_count == 2


def test_recall_pubsub_redelivery_uses_stable_ledger_command_and_isolated_scope():
    client = TestClient(main.app)
    event = {
        "event_type": "RECALL_NOTICE_RECEIVED",
        "tenant_id": "east-bay-food-bank",
        "coordinator_id": "COORD-ALT",
        "incident_id": "INC-RECALL-ALT",
        "lot_id": "LOT-RECALL-ALT",
        "notice_text": "Representative recall notice",
    }
    db = MagicMock()
    snapshot = MagicMock()
    snapshot.execute_sql.return_value = [("WAITING_FOR_EVENTS", "CHK-ALT", "rev08")]
    db.snapshot.return_value.__enter__.return_value = snapshot
    results = [
        {"receipt": {"receipt_id": "RCT-RECALL", "status": "SUCCESS"},
         "idempotent_replay": False},
        {"receipt": {"receipt_id": "RCT-RECALL", "status": "SUCCESS"},
         "idempotent_replay": True},
    ]
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "get_spanner_database", return_value=db
    ), patch.object(main, "execute_ledger_command", side_effect=results) as ledger:
        first = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event, "recall-message-1"),
        )
        duplicate = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event, "recall-message-1"),
        )

    assert first.status_code == duplicate.status_code == 200
    assert first.json()["incident"]["incident_id"] == "INC-RECALL-ALT"
    assert duplicate.json()["idempotent_redelivery"] is True
    assert duplicate.json()["ledger_receipt"]["receipt_id"] == "RCT-RECALL"
    assert ledger.call_args_list[0].kwargs["tenant_id"] == "east-bay-food-bank"
    assert ledger.call_args_list[0].kwargs["payload"]["source_event_id"] == "recall-message-1"
    assert ledger.call_args_list[0].kwargs["idempotency_key"] == ledger.call_args_list[1].kwargs["idempotency_key"]


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


def test_task_redelivery_reuses_deterministic_ledger_idempotency_key():
    client = TestClient(main.app)
    result = {
        "receipt": {"receipt_id": "RCT-TASK-REPLAY", "status": "SUCCESS"},
        "idempotent_replay": True,
    }
    request = {
        "incident_id": "INC-RECALL-01",
        "site_id": "SITE-01",
        "task_decision_id": "task-redelivery",
    }
    headers = {
        "Authorization": "Bearer signed",
        "X-CloudTasks-TaskName": "task-redelivery",
        "X-CloudTasks-QueueName": "full-shelf-deadlines",
    }
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "execute_ledger_command", return_value=result
    ) as ledger:
        first = client.post("/api/v1/incidents/site01-deadline", headers=headers, json=request)
        second = client.post("/api/v1/incidents/site01-deadline", headers=headers, json=request)

    assert first.status_code == second.status_code == 200
    assert ledger.call_count == 2
    first_key = ledger.call_args_list[0].kwargs["idempotency_key"]
    second_key = ledger.call_args_list[1].kwargs["idempotency_key"]
    assert first_key == second_key == "cloud-task:task-redelivery"
