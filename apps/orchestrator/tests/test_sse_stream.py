import pytest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


def test_sse_stream_reads_committed_spanner_events():
    from main import app
    client = TestClient(app)

    mock_db = MagicMock()
    mock_snapshot = MagicMock()
    
    mock_receipts = [
        ("RCT-001", "ACT-001", "rev07", "ALLOCATE", "COMMITTED", "Order O201 allocated", "2026-08-08T00:00:00Z"),
        ("RCT-002", "ACT-002", "rev08", "RECALL_PAUSE", "COMMITTED", "Recall LTC-4471 paused", "2026-08-08T01:00:00Z"),
    ]
    mock_snapshot.execute_sql.return_value = mock_receipts
    mock_db.snapshot.return_value.__enter__.return_value = mock_snapshot

    with patch("main.get_spanner_database", return_value=mock_db):
        response = client.get("/api/v1/projections/stream?tenant_id=east-bay-food-bank")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = response.text
        assert "RCT-001" in body
        assert "RCT-002" in body


def test_sse_stream_supports_last_event_id_cursor():
    from main import app
    client = TestClient(app)

    mock_db = MagicMock()
    mock_snapshot = MagicMock()
    
    mock_receipts = [
        ("RCT-001", "ACT-001", "rev07", "ALLOCATE", "COMMITTED", "Order O201 allocated", "2026-08-08T00:00:00Z"),
        ("RCT-002", "ACT-002", "rev08", "RECALL_PAUSE", "COMMITTED", "Recall LTC-4471 paused", "2026-08-08T01:00:00Z"),
    ]
    mock_snapshot.execute_sql.return_value = mock_receipts
    mock_db.snapshot.return_value.__enter__.return_value = mock_snapshot

    with patch("main.get_spanner_database", return_value=mock_db):
        headers = {"Last-Event-ID": "evt-RCT-001"}
        response = client.get("/api/v1/projections/stream?tenant_id=east-bay-food-bank", headers=headers)
        assert response.status_code == 200
        body = response.text
        # Event RCT-001 should be skipped due to Last-Event-ID
        assert "RCT-002" in body
