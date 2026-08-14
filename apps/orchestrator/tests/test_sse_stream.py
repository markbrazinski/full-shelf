import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


orchestrator_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if orchestrator_src not in sys.path:
    sys.path.insert(0, orchestrator_src)

import main as orchestrator_main


class ConnectedRequest:
    async def is_disconnected(self):
        return False


class DisconnectAfterFirstPoll:
    def __init__(self):
        self.calls = 0

    async def is_disconnected(self):
        self.calls += 1
        return self.calls > 1


def _receipt(receipt_id, timestamp):
    return (
        receipt_id,
        f"ACT-{receipt_id}",
        "rev08",
        "RECORD_ACKNOWLEDGMENT_HOLD",
        "SUCCESS",
        f"Committed {receipt_id}",
        timestamp,
        "0123456789abcdef0123456789abcdef",
        "orchestrator@example.iam.gserviceaccount.com",
    )


async def _collect(generator):
    return [chunk async for chunk in generator]


def test_cursor_round_trip_binds_ordering_timestamp_and_receipt_id():
    timestamp = datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc)
    event_id = orchestrator_main._encode_receipt_cursor(timestamp, "RCT-001")

    decoded_timestamp, decoded_receipt = orchestrator_main._decode_receipt_cursor(event_id)

    assert event_id.startswith("r1.")
    assert decoded_timestamp == timestamp
    assert decoded_receipt == "RCT-001"


def test_resume_query_is_strictly_after_durable_ordered_cursor():
    db = MagicMock()
    snapshot = MagicMock()
    snapshot.execute_sql.return_value = []
    db.snapshot.return_value.__enter__.return_value = snapshot
    cursor = (datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc), "RCT-001")

    orchestrator_main._query_committed_receipts_after(
        db, tenant_id="east-bay-food-bank", cursor=cursor
    )

    sql = snapshot.execute_sql.call_args.args[0]
    params = snapshot.execute_sql.call_args.kwargs["params"]
    assert "timestamp > @cursor_timestamp" in sql
    assert "timestamp = @cursor_timestamp AND receipt_id > @cursor_receipt_id" in sql
    assert "ORDER BY timestamp ASC, receipt_id ASC" in sql
    assert params["cursor_timestamp"] == cursor[0]
    assert params["cursor_receipt_id"] == "RCT-001"


def test_stream_stays_open_and_emits_new_commit_without_reconnect():
    timestamp = datetime(2026, 8, 14, 2, 1, tzinfo=timezone.utc)
    calls = [[], [_receipt("RCT-NEW", timestamp)]]

    with patch.object(orchestrator_main, "_query_committed_receipts_after", side_effect=calls) as query:
        chunks = asyncio.run(_collect(orchestrator_main._stream_committed_receipts(
            request=ConnectedRequest(),
            db=MagicMock(),
            tenant_id="east-bay-food-bank",
            cursor=None,
            poll_interval=0.001,
            max_polls=2,
        )))

    assert query.call_count == 2
    assert len(chunks) == 1
    assert "event: projection_update" in chunks[0]
    assert "RCT-NEW" in chunks[0]
    assert "0123456789abcdef0123456789abcdef" in chunks[0]
    assert "orchestrator@example.iam.gserviceaccount.com" in chunks[0]


def test_stream_advances_cursor_without_skip_or_duplicate():
    first_at = datetime(2026, 8, 14, 2, 1, tzinfo=timezone.utc)
    second_at = first_at + timedelta(seconds=1)
    calls = [
        [_receipt("RCT-001", first_at)],
        [_receipt("RCT-002", second_at)],
        [],
    ]

    with patch.object(orchestrator_main, "_query_committed_receipts_after", side_effect=calls) as query:
        chunks = asyncio.run(_collect(orchestrator_main._stream_committed_receipts(
            request=ConnectedRequest(),
            db=MagicMock(),
            tenant_id="east-bay-food-bank",
            cursor=None,
            poll_interval=0.001,
            max_polls=3,
        )))

    assert len(chunks) == 2
    assert sum("RCT-001" in chunk for chunk in chunks) == 1
    assert sum("RCT-002" in chunk for chunk in chunks) == 1
    second_cursor = query.call_args_list[1].kwargs["cursor"]
    third_cursor = query.call_args_list[2].kwargs["cursor"]
    assert second_cursor == (first_at, "RCT-001")
    assert third_cursor == (second_at, "RCT-002")


def test_disconnect_stops_polling_cleanly():
    with patch.object(orchestrator_main, "_query_committed_receipts_after", return_value=[]) as query:
        chunks = asyncio.run(_collect(orchestrator_main._stream_committed_receipts(
            request=DisconnectAfterFirstPoll(),
            db=MagicMock(),
            tenant_id="east-bay-food-bank",
            cursor=None,
            poll_interval=0.001,
        )))

    assert chunks == []
    assert query.call_count == 1


def test_authoritative_read_failure_emits_truthful_error_then_closes():
    with patch.object(
        orchestrator_main,
        "_query_committed_receipts_after",
        side_effect=RuntimeError("managed read unavailable"),
    ):
        chunks = asyncio.run(_collect(orchestrator_main._stream_committed_receipts(
            request=ConnectedRequest(),
            db=MagicMock(),
            tenant_id="east-bay-food-bank",
            cursor=None,
            poll_interval=0.001,
        )))

    assert len(chunks) == 1
    assert "event: projection_error" in chunks[0]
    assert "AUTHORITATIVE_EVENT_READ_UNAVAILABLE" in chunks[0]
    assert '"classification": "FAILED"' in chunks[0]


def test_endpoint_rejects_malformed_last_event_id_before_streaming():
    client = TestClient(orchestrator_main.app)
    with (
        patch.object(orchestrator_main, "verify_judge_key"),
        patch.object(orchestrator_main, "get_spanner_database", return_value=MagicMock()),
    ):
        response = client.get(
            "/api/v1/projections/stream?tenant_id=east-bay-food-bank",
            headers={"Last-Event-ID": "evt-legacy-ambiguous"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_LAST_EVENT_ID"
