import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


orchestrator_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if orchestrator_src not in sys.path:
    sys.path.insert(0, orchestrator_src)

import main as orchestrator_main


TRACE_ID = "0123456789abcdef0123456789abcdef"
SPAN_ID = "0123456789abcdef"


def _evidence_database():
    db = MagicMock()
    snapshot = MagicMock()
    now = datetime(2026, 8, 14, 2, 40, tzinfo=timezone.utc)
    snapshot.execute_sql.side_effect = [
        [("rev08",)],
        [("INC-RECALL-01", "PARTIALLY_CONTAINED", "PARTIALLY_CONTAINED", "LTC-4471")],
        [(42,)],
        [("RCT-LIVE", "CMD-LIVE", "RECORD_ACKNOWLEDGMENT_HOLD", "SUCCESS", 2,
          TRACE_ID, "orchestrator@example.com", now)],
        [("message-123", "PLAN_NEXT_DAY_REQUESTED", "ACCEPTED", now)],
    ]
    db.snapshot.return_value.__enter__.return_value = snapshot
    return db


def test_evidence_trace_id_is_actual_inbound_execution_trace_and_config_is_not_live():
    client = TestClient(orchestrator_main.app)
    graph = {
        "lot_id": "LTC-4471",
        "unique_current_cases": 96,
        "max_path_depth": 2,
        "query_engine": "SPANNER_GRAPH_GQL",
    }
    with (
            patch.object(orchestrator_main, "_verify_internal_workload"),
        patch.object(orchestrator_main, "get_spanner_database", return_value=_evidence_database()),
        patch.object(orchestrator_main, "_run_managed_custody_graph", return_value=graph),
    ):
        response = client.get(
            "/api/v1/evidence/system",
            headers={"traceparent": f"00-{TRACE_ID}-{SPAN_ID}-01"},
        )

    assert response.status_code == 200
    body = response.json()
    assert response.headers["X-Full-Shelf-Trace-Id"] == TRACE_ID
    assert body["request_execution"]["trace_id"] == TRACE_ID
    assert body["managed_resources"]["cloud_trace"]["trace_id"] == TRACE_ID
    assert body["managed_resources"]["cloud_trace"]["classification"] == "NOT_PROVEN"
    assert body["managed_resources"]["gemini_model"]["classification"] == "DESIGNED"
    assert body["managed_resources"]["model_armor"]["classification"] == "DESIGNED"
    assert body["managed_resources"]["build_provenance"]["classification"] == "DESIGNED"
    assert body["latest_ledger_receipt"]["classification"] == "OBSERVED_LIVE"


def test_evidence_managed_failures_downgrade_instead_of_claiming_success():
    client = TestClient(orchestrator_main.app)
    db = MagicMock()
    snapshot = MagicMock()
    snapshot.execute_sql.side_effect = RuntimeError("Spanner unavailable")
    db.snapshot.return_value.__enter__.return_value = snapshot

    with (
            patch.object(orchestrator_main, "_verify_internal_workload"),
        patch.object(orchestrator_main, "get_spanner_database", return_value=db),
        patch.object(
            orchestrator_main,
            "_run_managed_custody_graph",
            side_effect=RuntimeError("Graph unavailable"),
        ),
    ):
        response = client.get("/api/v1/evidence/system")

    assert response.status_code == 200
    body = response.json()
    assert body["overall_classification"] == "FAILED"
    assert set(body["failed_checks"]) == {
        "spanner_ground_truth",
        "latest_ledger_receipt",
        "latest_inbound_event",
        "spanner_graph",
    }
    assert body["spanner_ground_truth"]["classification"] == "FAILED"
    assert body["latest_ledger_receipt"]["classification"] == "FAILED"
    assert body["managed_resources"]["spanner_graph"]["classification"] == "FAILED"
