import importlib.util
import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


orchestrator_main_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src", "main.py")
)
spec = importlib.util.spec_from_file_location("orchestrator_next_day_main", orchestrator_main_path)
orchestrator_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrator_main)


def authoritative_rows(sql):
    if "incident_id = 'INC-RECALL-01'" in sql:
        return [("PARTIALLY_CONTAINED",)]
    if "FROM MovementBarriers" in sql:
        return [("BARRIER-ALT", "LTC-4471", "ACTIVE")]
    if "FROM RecoveryShortfalls" in sql:
        return [("SHORT-ALT", "AG03", 20, "OPEN")]
    if "incident_type = 'DEADLINE_HOLD'" in sql:
        return [("HOLD-ALT", '{"site_id":"SITE-01","unconfirmed_cases":8}',
                 "ACKNOWLEDGMENT_HOLD_ACTIVE")]
    if "FROM Lots" in sql:
        return [("LTC-5090", 40)]
    if "FROM Vehicles" in sql:
        return [("TRUCK-02", 60, 36)]
    raise AssertionError(sql)


def test_next_day_plan_is_dynamic_authoritative_and_ledger_bound():
    client = TestClient(orchestrator_main.app)
    mock_db = MagicMock()
    snapshot = mock_db.snapshot.return_value.__enter__.return_value
    snapshot.execute_sql.side_effect = lambda sql, **kwargs: authoritative_rows(sql)

    ledger = {
        "receipt": {"receipt_id": "RCT-NEXT-DAY-ALT", "status": "SUCCESS"},
        "idempotent_replay": False,
        "additional_mutations": 6,
    }
    with patch.object(orchestrator_main, "get_spanner_database", return_value=mock_db), patch.object(
        orchestrator_main, "get_judge_api_key", return_value="test-key"
    ), patch.object(orchestrator_main, "execute_ledger_command", return_value=ledger) as execute:
        with patch.object(
            orchestrator_main,
            "datetime",
            wraps=orchestrator_main.datetime,
        ):
            response = client.post(
                "/api/v1/orchestrator/next-day-plan/generate?tenant_id=east-bay-food-bank",
                headers={"X-Full-Shelf-API-Key": "test-key"},
            )

    assert response.status_code == 200
    draft = response.json()["next_day_draft"]
    assert draft["revision"] == "rev01"
    assert draft["status"] == "DRAFT_WITH_CONSTRAINTS — HUMAN APPROVAL REQUIRED"
    assert draft["inherited_constraints"][0]["affected_lot"] == "LTC-4471"
    assert draft["inherited_constraints"][1]["shortfall_cases"] == 20
    assert draft["inherited_constraints"][2]["unconfirmed_cases"] == 8
    command = execute.call_args.kwargs
    assert command["command_type"] == "CREATE_NEXT_DAY_DRAFT"
    assert command["expected_plan_revision"] == "rev08"
    assert command["payload"]["human_approval_required"] is True
    executed_sql = [call.args[0] for call in snapshot.execute_sql.call_args_list]
    assert any("hazard_status = 'CLEAR_SAFE'" in sql for sql in executed_sql)
    mock_db.snapshot.assert_called_once_with(multi_use=True)


def test_spanner_database_handle_is_cached_per_service_instance():
    orchestrator_main.get_spanner_database.cache_clear()
    mock_database = MagicMock()
    mock_instance = MagicMock()
    mock_instance.database.return_value = mock_database
    mock_client = MagicMock()
    mock_client.instance.return_value = mock_instance

    with patch.object(orchestrator_main.spanner, "Client", return_value=mock_client):
        first = orchestrator_main.get_spanner_database()
        second = orchestrator_main.get_spanner_database()

    assert first is mock_database
    assert second is mock_database
    mock_client.instance.assert_called_once_with(orchestrator_main.SPANNER_INSTANCE)
    mock_instance.database.assert_called_once_with(orchestrator_main.SPANNER_DATABASE)
    orchestrator_main.get_spanner_database.cache_clear()


def test_pubsub_next_day_delivery_requires_verified_identity_and_uses_publish_date():
    client = TestClient(orchestrator_main.app)
    caller = MagicMock(
        email="delivery@example.iam.gserviceaccount.com",
        audience="https://orchestrator.example.run.app",
    )
    result = {"status": "NEXT_DAY_DRAFT_CREATED", "idempotent_replay": False}
    envelope = {
        "message": {
            "messageId": "managed-message-123",
            "publishTime": "2026-08-14T00:30:00Z",
            "data": "eyJldmVudF90eXBlIjoiUExBTl9ORVhUX0RBWV9SRVFVRVNURUQiLCJ0ZW5hbnRfaWQiOiJlYXN0LWJheS1mb29kLWJhbmsifQ==",
        }
    }
    with patch.object(orchestrator_main, "_verify_managed_callback", return_value=caller), patch.object(
        orchestrator_main, "_generate_next_day_plan", return_value=result
    ) as generate:
        response = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=envelope,
        )
    assert response.status_code == 200
    assert response.json()["delivery_identity"] == caller.email
    assert generate.call_args.kwargs == {
        "tenant_id": "east-bay-food-bank",
        "source_event_id": "managed-message-123",
        "source_publish_time": "2026-08-14T00:30:00Z",
    }


def test_pubsub_push_rejects_missing_identity_before_interpretation():
    client = TestClient(orchestrator_main.app)
    with patch.object(
        orchestrator_main,
        "_verify_managed_callback",
        side_effect=orchestrator_main.HTTPException(401, "token required"),
    ):
        response = client.post("/api/v1/orchestrator/pubsub/push", json={})
    assert response.status_code == 401


def test_pubsub_redelivery_preserves_source_idempotency_inputs():
    client = TestClient(orchestrator_main.app)
    caller = MagicMock(
        email="delivery@example.iam.gserviceaccount.com",
        audience="https://orchestrator.example.run.app",
    )
    envelope = {
        "message": {
            "messageId": "managed-message-redelivery-123",
            "publishTime": "2026-08-14T00:30:00Z",
            "data": "eyJldmVudF90eXBlIjoiUExBTl9ORVhUX0RBWV9SRVFVRVNURUQiLCJ0ZW5hbnRfaWQiOiJlYXN0LWJheS1mb29kLWJhbmsifQ==",
        }
    }
    result = {"status": "NEXT_DAY_DRAFT_CREATED", "idempotent_replay": False}
    with patch.object(orchestrator_main, "_verify_managed_callback", return_value=caller), patch.object(
        orchestrator_main, "_generate_next_day_plan", return_value=result
    ) as generate:
        first = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=envelope,
        )
        second = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=envelope,
        )

    assert first.status_code == second.status_code == 200
    assert generate.call_count == 2
    assert generate.call_args_list[0].kwargs == generate.call_args_list[1].kwargs
    assert generate.call_args_list[0].kwargs["source_event_id"] == "managed-message-redelivery-123"
