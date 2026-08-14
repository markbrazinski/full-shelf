import importlib.util
import os
import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from google.api_core.exceptions import AlreadyExists

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


def _task_payload(task_id):
    return {
        "tenant_id": "east-bay-food-bank",
        "incident_id": "INC-RECALL-01",
        "hold_incident_id": "INC-RECALL-01-HOLD-SITE01",
        "coordinator_id": "COORD-2026-0807",
        "lot_id": "LTC-4471",
        "site_id": "SITE-01",
        "unconfirmed_cases": 8,
        "task_decision_id": task_id,
        "correlation_trace_id": "0123456789abcdef0123456789abcdef",
    }


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
            json=_task_payload("task-forged"),
        )
    assert response.status_code == 401
    ledger.assert_not_called()


def _pubsub_envelope(
    event, message_id="scheduler-message-1",
    publish_time="2026-08-14T12:30:00Z",
):
    return {
        "message": {
            "messageId": message_id,
            "publishTime": publish_time,
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
             "on_hand_cases": 2, "acknowledgment_status": "CONFIRMED"},
            {"node_id": "NODE-AG", "node_type": "AGENCY", "name": "Agency",
             "on_hand_cases": 2, "acknowledgment_status": "CONFIRMED"},
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
    event = {"event_type": "PLAN_DAY_REQUESTED", "tenant_id": "audit-canonical",
             "operating_plan": _minimal_operating_plan()}
    results = [
        {"status": "DAILY_PLAN_GENERATED_REV07", "idempotent_replay": False},
        {"status": "DAILY_PLAN_EXISTS_IDEMPOTENT", "idempotent_replay": True},
    ]
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_resolve_authority_scope"
    ), patch.object(main, "_generate_daily_morning_plan", side_effect=results
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
    assert generate.call_args_list[0].kwargs["request"].operating_day == "2026-08-14"
    assert generate.call_args_list[0].kwargs["request"].tenant_id == "audit-canonical"


def test_managed_publish_time_uses_food_bank_day_boundary():
    before_midnight = datetime.fromisoformat("2026-08-15T06:59:59+00:00")
    at_midnight = datetime.fromisoformat("2026-08-15T07:00:00+00:00")
    with patch.object(main, "OPERATING_TIME_ZONE", "America/Los_Angeles"):
        assert main._operating_day_from_managed_publish_time(before_midnight) == (
            "2026-08-14"
        )
        assert main._operating_day_from_managed_publish_time(at_midnight) == (
            "2026-08-15"
        )


def test_same_local_day_is_stable_and_next_local_day_changes_authority():
    client = TestClient(main.app)
    event = {
        "event_type": "PLAN_DAY_REQUESTED", "tenant_id": "audit-canonical",
        "operating_plan": _minimal_operating_plan(),
    }
    stable = {"status": "OK", "idempotent_replay": True}
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_resolve_authority_scope"
    ), patch.object(main, "_generate_daily_morning_plan", return_value=stable) as generate:
        for message_id, publish_time in (
            ("managed-a", "2026-08-14T05:00:00Z"),
            ("managed-b", "2026-08-14T06:59:59Z"),
            ("managed-c", "2026-08-14T07:00:00Z"),
        ):
            response = client.post(
                "/api/v1/orchestrator/pubsub/push",
                headers={"Authorization": "Bearer signed"},
                json=_pubsub_envelope(event, message_id, publish_time),
            )
            assert response.status_code == 200

    requests = [call.kwargs["request"] for call in generate.call_args_list]
    assert [request.operating_day for request in requests] == [
        "2026-08-13", "2026-08-13", "2026-08-14"
    ]
    assert [main.operating_day_authority_id(request.tenant_id, request.operating_day)
            for request in requests] == [
        "audit-canonical-20260813",
        "audit-canonical-20260813",
        "audit-canonical-20260814",
    ]


def test_recurring_daily_rejects_payload_day_and_caller_timestamp():
    client = TestClient(main.app)
    event = {
        "event_type": "PLAN_DAY_REQUESTED", "tenant_id": "audit-canonical",
        "operating_day": "2099-01-01",
        "timestamp": "2099-01-01T00:00:00Z",
        "operating_plan": _minimal_operating_plan(),
    }
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_generate_daily_morning_plan"
    ) as generate:
        response = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event),
        )
    assert response.status_code == 200
    assert response.json()["disposition"] == "PERMANENTLY_REJECTED_ACKNOWLEDGED"
    generate.assert_not_called()


def test_distinct_scheduler_message_ids_resolve_to_one_operating_day_command():
    request = main.OperatingDayRequest.model_validate({
        "event_type": "PLAN_DAY_REQUESTED",
        "tenant_id": "audit-canonical",
        "operating_day": "2026-08-14",
        "operating_plan": _minimal_operating_plan(),
    })
    first = {
        "receipt": {"receipt_id": "RCT-STABLE", "status": "SUCCESS"},
        "idempotent_replay": False,
    }
    duplicate = {
        "receipt": {"receipt_id": "RCT-STABLE", "status": "SUCCESS"},
        "idempotent_replay": True,
    }
    with patch.object(main, "_resolve_authority_scope"), patch.object(
        main, "execute_ledger_command", side_effect=[first, duplicate]
    ) as ledger:
        first_result = main._generate_daily_morning_plan(request=request)
        duplicate_result = main._generate_daily_morning_plan(request=request)

    first_command = ledger.call_args_list[0].kwargs
    duplicate_command = ledger.call_args_list[1].kwargs
    assert first_command["tenant_id"] == duplicate_command["tenant_id"] == (
        "audit-canonical-20260814"
    )
    assert first_command["idempotency_key"] == duplicate_command["idempotency_key"]
    assert first_command["payload"] == duplicate_command["payload"]
    assert "source_publish_time" not in first_command["payload"]
    assert "message_id" not in first_command["payload"]
    assert first_result["ledger_receipt"]["receipt_id"] == "RCT-STABLE"
    assert duplicate_result["ledger_receipt"]["receipt_id"] == "RCT-STABLE"
    assert duplicate_result["idempotent_replay"] is True


def test_daily_qualification_profile_is_not_an_operating_day_contract():
    client = TestClient(main.app)
    event = {
        "event_type": "PLAN_DAY_REQUESTED",
        "qualification_profile": "canonical",
        "operating_plan": _minimal_operating_plan(),
    }
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_generate_daily_morning_plan"
    ) as generate:
        response = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event),
        )

    assert response.status_code == 200
    assert response.json()["disposition"] == "PERMANENTLY_REJECTED_ACKNOWLEDGED"
    generate.assert_not_called()


def test_authenticated_poison_pubsub_message_is_acked_2xx_without_mutation():
    client = TestClient(main.app)
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "execute_ledger_command"
    ) as ledger:
        response = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope({"event_type": "OBSOLETE_EVENT"}, "old-poison-1"),
        )

    assert response.status_code == 200
    assert response.json()["disposition"] == "PERMANENTLY_REJECTED_ACKNOWLEDGED"
    assert response.json()["mutations_applied"] == 0
    ledger.assert_not_called()


def test_authenticated_stale_pubsub_message_is_acked_without_interpretation():
    client = TestClient(main.app)
    envelope = _pubsub_envelope(
        {"event_type": "RECALL_NOTICE_RECEIVED", "tenant_id": "east-bay-food-bank"},
        "historical-backlog-1",
    )
    envelope["message"]["publishTime"] = (
        datetime.now(timezone.utc) - timedelta(days=2)
    ).isoformat().replace("+00:00", "Z")
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_resolve_authority_scope"
    ) as resolve, patch.object(main, "execute_ledger_command") as ledger:
        response = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=envelope,
        )

    assert response.status_code == 200
    assert response.json()["reason"] == "STALE_PUBSUB_EVENT"
    assert response.json()["disposition"] == "STALE_ACKNOWLEDGED"
    assert response.json()["mutations_applied"] == 0
    resolve.assert_not_called()
    ledger.assert_not_called()


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
    assert all(
        call.kwargs["source_operating_day"] == "2026-08-14"
        for call in generate.call_args_list
    )
    assert all("source_event_id" not in call.kwargs for call in generate.call_args_list)


def test_next_day_qualification_profile_is_permanently_rejected():
    client = TestClient(main.app)
    event = {
        "event_type": "PLAN_NEXT_DAY_REQUESTED",
        "qualification_profile": "canonical",
    }
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_generate_next_day_plan"
    ) as generate:
        response = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event),
        )
    assert response.status_code == 200
    assert response.json()["disposition"] == "PERMANENTLY_REJECTED_ACKNOWLEDGED"
    assert response.json()["mutations_applied"] == 0
    generate.assert_not_called()


def test_next_day_transient_persistence_failure_remains_retryable():
    client = TestClient(main.app)
    event = {"event_type": "PLAN_NEXT_DAY_REQUESTED", "tenant_id": "east-bay-food-bank"}
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_resolve_authority_scope"
    ), patch.object(
        main, "_generate_next_day_plan",
        side_effect=main.HTTPException(503, "AUTHORITATIVE_CONTINUITY_READ_UNAVAILABLE"),
    ):
        response = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event),
        )
    assert response.status_code == 503


def test_next_day_permanent_business_rejection_is_acked_without_mutation():
    client = TestClient(main.app)
    event = {"event_type": "PLAN_NEXT_DAY_REQUESTED", "tenant_id": "east-bay-food-bank"}
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "_resolve_authority_scope"
    ), patch.object(
        main, "_generate_next_day_plan",
        side_effect=main.HTTPException(409, "NEXT_DAY_CONSTRAINTS_INCOMPLETE"),
    ), patch.object(main, "execute_ledger_command") as ledger:
        response = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=_pubsub_envelope(event),
        )
    assert response.status_code == 200
    assert response.json()["disposition"] == "PERMANENTLY_REJECTED_ACKNOWLEDGED"
    assert response.json()["mutations_applied"] == 0
    ledger.assert_not_called()


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
        {"hero_loop_status": "COMPLETED", "trace_id": "trace-1"},
        {"hero_loop_status": "COMPLETED", "trace_id": "trace-1"},
    ]
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "get_spanner_database", return_value=db
    ), patch.object(main, "_execute_managed_recall_event", side_effect=results) as execute:
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
    assert first.json()["hero_loop_result"]["hero_loop_status"] == "COMPLETED"
    assert duplicate.json()["hero_loop_result"] == first.json()["hero_loop_result"]
    assert execute.call_args_list[0].kwargs["tenant_id"] == "east-bay-food-bank"
    assert execute.call_args_list[0].kwargs["source_event_id"] == "recall-message-1"
    assert execute.call_args_list[0].kwargs["recalled_lot_id"] == "LOT-RECALL-ALT"


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
            json=_task_payload("task-alt"),
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
            tenant_id="audit-tenant",
            incident_id="INC-RECALL-ALT",
            hold_incident_id="INC-RECALL-ALT-HOLD-SITE-X",
            coordinator_id="COORD-ALT",
            lot_id="LOT-ALT",
            site_id="SITE-X",
            unconfirmed_cases=3,
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
    body = json.loads(task["http_request"]["body"])
    assert body["tenant_id"] == "audit-tenant"
    assert body["site_id"] == "SITE-X"
    assert body["unconfirmed_cases"] == 3
    assert result["correlation_trace_id"] == "0123456789abcdef0123456789abcdef"


def test_task_creation_treats_a_deterministic_duplicate_as_success():
    client = MagicMock()
    client.queue_path.return_value = "projects/p/locations/l/queues/q"
    client.task_path.return_value = "projects/p/locations/l/queues/q/tasks/t"
    client.create_task.side_effect = AlreadyExists("duplicate")
    with patch("google.cloud.tasks_v2.CloudTasksClient", return_value=client):
        result = main.schedule_site01_deadline_task(
            tenant_id="audit-tenant",
            incident_id="INC-ALT",
            hold_incident_id="INC-ALT-HOLD",
            coordinator_id="COORD-ALT",
            lot_id="LOT-ALT",
            site_id="SITE-ALT",
            unconfirmed_cases=3,
            task_id="t",
            orchestrator_url="https://orchestrator.example.run.app",
            oidc_audience="https://orchestrator.example.run.app",
            delivery_service_account="delivery@example.iam.gserviceaccount.com",
            trace_id="0123456789abcdef0123456789abcdef",
        )

    assert result["status"] == "ALREADY_SCHEDULED"
    assert result["task_name"].endswith("/tasks/t")


def test_task_redelivery_reuses_deterministic_ledger_idempotency_key():
    client = TestClient(main.app)
    result = {
        "receipt": {"receipt_id": "RCT-TASK-REPLAY", "status": "SUCCESS"},
        "idempotent_replay": True,
    }
    request = _task_payload("task-redelivery")
    headers = {
        "Authorization": "Bearer signed",
        "X-CloudTasks-TaskName": "task-redelivery",
        "X-CloudTasks-QueueName": "full-shelf-deadlines",
        "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
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
    assert first_key == second_key
    assert first_key.startswith("cloud-task:")


def test_two_distinct_task_names_share_one_event_idempotency_key():
    client = TestClient(main.app)
    result = {
        "receipt": {"receipt_id": "RCT-TASK-ONE", "status": "SUCCESS"},
        "idempotent_replay": True,
    }
    first_payload = _task_payload("task-delivery-a")
    second_payload = _task_payload("task-delivery-b")
    first_payload["event_idempotency_key"] = "site01-event-shared"
    second_payload["event_idempotency_key"] = "site01-event-shared"
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "execute_ledger_command", return_value=result
    ) as ledger:
        for task_name, body in (
            ("task-delivery-a", first_payload), ("task-delivery-b", second_payload)
        ):
            response = client.post(
                "/api/v1/incidents/site01-deadline",
                headers={
                    "Authorization": "Bearer signed",
                    "X-CloudTasks-TaskName": task_name,
                    "X-CloudTasks-QueueName": "full-shelf-deadlines",
                    "traceparent": (
                        "00-0123456789abcdef0123456789abcdef-"
                        "0123456789abcdef-01"
                    ),
                },
                json=body,
            )
            assert response.status_code == 200

    assert ledger.call_count == 2
    assert {
        call.kwargs["idempotency_key"] for call in ledger.call_args_list
    } == {ledger.call_args_list[0].kwargs["idempotency_key"]}
    assert {
        call.kwargs["payload"]["task_name"] for call in ledger.call_args_list
    } == {"site01-event-shared"}


def test_task_delivery_emits_committed_idempotency_evidence():
    client = TestClient(main.app)
    request = _task_payload("task-evidence")
    request["event_idempotency_key"] = "site01-event-evidence"
    result = {
        "receipt": {"receipt_id": "RCT-TASK-EVIDENCE", "status": "SUCCESS"},
        "idempotent_replay": True,
    }
    with patch.object(main, "_verify_managed_callback", return_value=CALLER), patch.object(
        main, "execute_ledger_command", return_value=result
    ), patch.object(main.logger, "warning") as log_warning:
        response = client.post(
            "/api/v1/incidents/site01-deadline",
            headers={
                "Authorization": "Bearer signed",
                "X-CloudTasks-TaskName": "task-evidence",
                "X-CloudTasks-QueueName": "full-shelf-deadlines",
                "traceparent": (
                    "00-0123456789abcdef0123456789abcdef-"
                    "0123456789abcdef-01"
                ),
            },
            json=request,
        )

    assert response.status_code == 200
    log_warning.assert_called_once_with(
        "cloud_task_delivery task_name=%s event_idempotency_key=%s "
        "receipt_id=%s idempotent_replay=%s",
        "task-evidence",
        "site01-event-evidence",
        "RCT-TASK-EVIDENCE",
        True,
    )


def test_application_escalation_schedules_task_from_authoritative_isolated_state():
    client = TestClient(main.app)
    db = MagicMock()
    snapshot = MagicMock()
    snapshot.execute_sql.side_effect = [
        [("PARTIALLY_CONTAINED",)],
        [("INC-HOLD-ALT", json.dumps({"site_id": "SITE-X", "unconfirmed_cases": 3}))],
    ]
    db.snapshot.return_value.__enter__.return_value = snapshot
    task_result = {
        "task_name": "projects/p/locations/l/queues/q/tasks/task-alt",
        "queue": "projects/p/locations/l/queues/q",
        "target_url": "https://orchestrator.example.run.app/api/v1/incidents/site01-deadline",
        "oidc_audience": "https://orchestrator.example.run.app",
        "delivery_service_account": "delivery@example.iam.gserviceaccount.com",
        "correlation_trace_id": "0123456789abcdef0123456789abcdef",
    }
    proposal = {
        "incident_id": "INC-RECALL-ALT", "hold_incident_id": "INC-HOLD-ALT",
        "coordinator_id": "COORD-ALT", "lot_id": "LOT-ALT",
        "site_id": "SITE-X", "unconfirmed_cases": 3,
    }
    with patch.object(main, "verify_judge_key"), patch.object(
        main, "get_spanner_database", return_value=db
    ), patch.object(
        main, "schedule_site01_deadline_task", return_value=task_result
    ) as schedule:
        response = client.post(
            "/api/v1/orchestrator/site01-escalation/schedule?tenant_id=east-bay-food-bank",
            json=proposal,
        )

    assert response.status_code == 200
    assert response.json()["task_name"].endswith("/tasks/task-alt")
    assert schedule.call_args.kwargs["incident_id"] == "INC-RECALL-ALT"
    assert schedule.call_args.kwargs["coordinator_id"] == "COORD-ALT"
    assert schedule.call_args.kwargs["site_id"] == "SITE-X"
    assert schedule.call_args.kwargs["unconfirmed_cases"] == 3
    assert snapshot.execute_sql.call_args_list[0].kwargs["params"]["incident_id"] == "INC-RECALL-ALT"
