import importlib.util
import os
import pathlib
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[3] / "packages/domain/tests")
)
from fleet_fakes import scripted_gemini  # noqa: E402


orchestrator_main_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src", "main.py")
)
spec = importlib.util.spec_from_file_location("orchestrator_next_day_main", orchestrator_main_path)
orchestrator_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrator_main)


def authoritative_rows(sql):
    if "incident_type = 'FOOD_SAFETY_RECALL'" in sql:
        return [("INC-ALTERED", "PARTIALLY_CONTAINED", "LOT-ALTERED")]
    if "FROM MovementBarriers" in sql:
        return [("BARRIER-ALT", "LOT-ALTERED", "ACTIVE")]
    if "FROM RecoveryShortfalls" in sql:
        return [("SHORT-ALT", "AGENCY-X", 7, "OPEN")]
    if "incident_type = 'DEADLINE_HOLD'" in sql:
        return [("HOLD-ALT", '{"parent_incident_id":"INC-ALTERED","site_id":"SITE-X","unconfirmed_cases":3}',
                 "ACKNOWLEDGMENT_HOLD_ACTIVE")]
    if "DISTINCT destination_agency_id" in sql:
        return [("AGENCY-X", "Altered Agency X")]
    if "FROM Lots" in sql:
        return [("SAFE-ALTERED", 21)]
    if "FROM Vehicles" in sql:
        return [("VEHICLE-ALTERED", 44, 19)]
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
    # Pin the clock so the derived next-day plan_id is stable, and script only
    # the Gemini network call. The ADK Runner, session service, agent classes,
    # schema handling and every validator stay real, and the handler still
    # drives the true run_fleet orchestration path. Without scripting, this
    # test reached for the live model and only passed because that failure
    # degraded quietly -- it failed the moment the network was blocked.
    frozen = datetime.fromisoformat("2026-08-14T17:00:00+00:00")

    class _FrozenDatetime(orchestrator_main.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz else frozen.replace(tzinfo=None)

    next_day_selection = {
        "selected_candidate_id": "PLAN-2026-08-15",
        "operating_objective": "NEXT_DAY_DRAFT",
        "affected_commitment_ids": ["CAND-PLAN-2026-08-15-SHORT-ALT"],
        "known_shortfalls": [
            {"agency_id": "AGENCY-X", "quantity": 7,
             "reason": "Confirmed safe supply does not cover the carried shortfall."},
        ],
        "cited_constraints": ["21 confirmed-safe cases available"],
        "tradeoffs": "Agency X keeps a truthful carried-forward shortfall.",
        "rationale": "Only feasible draft under the inherited constraints.",
        "confidence": 0.9,
    }
    with patch.object(orchestrator_main, "get_spanner_database", return_value=mock_db), patch.object(
        orchestrator_main, "_verify_internal_workload"
    ), patch.object(orchestrator_main, "execute_ledger_command", return_value=ledger) as execute:
        with patch.object(orchestrator_main, "datetime", _FrozenDatetime), scripted_gemini(
            overrides={"FulfillmentPlanningRecoveryAgent": next_day_selection}
        ):
            response = client.post(
                "/api/v1/orchestrator/next-day-plan/generate?tenant_id=east-bay-food-bank",
                headers={"X-Full-Shelf-API-Key": "test-key"},
            )

    assert response.status_code == 200
    draft = response.json()["next_day_draft"]
    assert draft["revision"] == "rev01"
    assert draft["status"] == "DRAFT_WITH_CONSTRAINTS — HUMAN APPROVAL REQUIRED"
    # Event 25 requires all FOUR inherited obligations. Indexed positionally
    # before, which silently tolerated a missing fourth entry.
    constraints = {c["type"]: c for c in draft["inherited_constraints"]}
    assert set(constraints) == {
        "LOT_MOVEMENT_BARRIER", "RECOVERY_PRIORITY",
        "ACKNOWLEDGMENT_HOLD", "UNRESOLVED_INCIDENT",
    }
    assert constraints["LOT_MOVEMENT_BARRIER"]["affected_lot"] == "LOT-ALTERED"
    assert constraints["RECOVERY_PRIORITY"]["shortfall_cases"] == 7
    assert constraints["ACKNOWLEDGMENT_HOLD"]["unconfirmed_cases"] == 3
    # The draft must not read as though the recall settled overnight.
    assert constraints["UNRESOLVED_INCIDENT"]["incident_id"] == "INC-ALTERED"
    assert constraints["UNRESOLVED_INCIDENT"]["incident_status"] == "PARTIALLY_CONTAINED"
    command = execute.call_args.kwargs
    assert command["command_type"] == "CREATE_NEXT_DAY_DRAFT"
    assert command["expected_plan_revision"] == "rev08"
    assert command["payload"]["human_approval_required"] is True
    assert command["incident_id"] == "INC-ALTERED"
    assert command["payload"]["shortfalls"][0]["agency_id"] == "AGENCY-X"
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
    result = {
        "status": "NEXT_DAY_DRAFT_CREATED", "idempotent_replay": False,
        "ledger_receipt": {"receipt_id": "RCT-NEXT"},
    }
    envelope = {
        "message": {
            "messageId": "managed-message-123",
            "publishTime": "2026-08-14T00:30:00Z",
            "data": "eyJldmVudF90eXBlIjoiUExBTl9ORVhUX0RBWV9SRVFVRVNURUQiLCJ0ZW5hbnRfaWQiOiJlYXN0LWJheS1mb29kLWJhbmsifQ==",
        }
    }
    frozen_now = datetime.fromisoformat("2026-08-14T00:31:00+00:00")
    with patch.object(orchestrator_main, "_utc_now", return_value=frozen_now), patch.object(
        orchestrator_main, "_verify_managed_callback", return_value=caller
    ), patch.object(
        orchestrator_main, "_generate_next_day_plan", return_value=result
    ) as generate:
        response = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=envelope,
        )
    assert response.status_code == 200
    assert response.json()["delivery_identity"] == caller.email
    assert generate.call_args.kwargs["tenant_id"] == "east-bay-food-bank"
    assert generate.call_args.kwargs["source_operating_day"] == "2026-08-13"
    assert "source_event_id" not in generate.call_args.kwargs
    assert "source_publish_time" not in generate.call_args.kwargs


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
    result = {
        "status": "NEXT_DAY_DRAFT_CREATED", "idempotent_replay": False,
        "ledger_receipt": {"receipt_id": "RCT-NEXT"},
    }
    frozen_now = datetime.fromisoformat("2026-08-14T00:31:00+00:00")
    with patch.object(orchestrator_main, "_utc_now", return_value=frozen_now), patch.object(
        orchestrator_main, "_verify_managed_callback", return_value=caller
    ), patch.object(
        orchestrator_main, "_generate_next_day_plan", return_value=result
    ) as generate:
        first = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=envelope,
        )
        second_envelope = {
            "message": {**envelope["message"], "messageId": "managed-message-redelivery-456"}
        }
        second = client.post(
            "/api/v1/orchestrator/pubsub/push",
            headers={"Authorization": "Bearer signed"},
            json=second_envelope,
        )

    assert first.status_code == second.status_code == 200
    assert generate.call_count == 2
    assert generate.call_args_list[0].kwargs["tenant_id"] == (
        generate.call_args_list[1].kwargs["tenant_id"]
    )
    assert generate.call_args_list[0].kwargs["source_operating_day"] == "2026-08-13"
    assert generate.call_args_list[1].kwargs["source_operating_day"] == "2026-08-13"
    assert all("source_event_id" not in call.kwargs for call in generate.call_args_list)
