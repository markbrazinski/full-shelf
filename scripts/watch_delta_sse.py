#!/usr/bin/env python3
"""Watch exactly the next committed isolated receipt over deployed SSE."""

from __future__ import annotations

import argparse
import base64
from datetime import timezone
import json

import httpx
from google.cloud import secretmanager, spanner


def receipt_cursor(timestamp, receipt_id):
    normalized = timestamp.astimezone(timezone.utc).isoformat()
    encoded = base64.urlsafe_b64encode(
        json.dumps([normalized, receipt_id], separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"r1.{encoded}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--database", default="full-shelf-audit-wp6-20260813")
    parser.add_argument("--expect-no-event", action="store_true")
    parser.add_argument("--read-timeout", type=float, default=90)
    parser.add_argument("--heartbeat-count", type=int, default=2)
    parser.add_argument(
        "--orchestrator-url",
        default="https://full-shelf-orchestrator-620464070103.us-central1.run.app",
    )
    args = parser.parse_args()
    if "audit" not in args.database or not args.tenant.startswith("audit-"):
        raise SystemExit("isolated audit scope required")

    database = spanner.Client(project="preflight-hackathon").instance(
        "fef-smoke-spanner"
    ).database(args.database)
    with database.snapshot() as snapshot:
        rows = list(snapshot.execute_sql(
            "SELECT timestamp, receipt_id FROM Receipts WHERE tenant_id=@tenant "
            "ORDER BY timestamp DESC, receipt_id DESC LIMIT 1",
            params={"tenant": args.tenant},
            param_types={"tenant": spanner.param_types.STRING},
        ))
    cursor = receipt_cursor(rows[0][0], rows[0][1]) if rows else None
    secret = secretmanager.SecretManagerServiceClient().access_secret_version(
        request={"name": "projects/preflight-hackathon/secrets/full-shelf-judge-api-key/versions/latest"}
    ).payload.data.decode().strip()
    headers = {"X-Full-Shelf-API-Key": secret}
    if cursor:
        headers["Last-Event-ID"] = cursor
    url = f"{args.orchestrator_url}/api/v1/projections/stream"
    with httpx.stream(
        "GET", url, params={"tenant_id": args.tenant}, headers=headers,
        timeout=httpx.Timeout(args.read_timeout, read=args.read_timeout),
    ) as response:
        response.raise_for_status()
        event = {}
        heartbeats = 0
        try:
            for line in response.iter_lines():
                if not line:
                    if event.get("event") == "projection_update":
                        payload = json.loads(event["data"])
                        observed = {
                            "connected_after_cursor": cursor,
                            "event_id": event.get("id"),
                            "receipt_id": payload["data"]["receipt_id"],
                            "command_type": payload["data"]["action_type"],
                            "correlation_trace_id": payload["data"]["correlation_trace_id"],
                            "classification": payload["classification"],
                        }
                        if args.expect_no_event:
                            raise RuntimeError(
                                "DUPLICATE_SSE_EVENT_OBSERVED "
                                + json.dumps(observed, sort_keys=True)
                            )
                        print(json.dumps(observed, sort_keys=True))
                        return
                    event = {}
                    continue
                if line.startswith(":"):
                    heartbeats += 1
                    if args.expect_no_event and heartbeats >= args.heartbeat_count:
                        print(json.dumps({
                            "connected_after_cursor": cursor,
                            "duplicate_events_observed": 0,
                            "heartbeats_observed": heartbeats,
                            "classification": "OBSERVED_LIVE",
                        }, sort_keys=True))
                        return
                    continue
                key, _, value = line.partition(":")
                event[key] = value.lstrip()
        except httpx.ReadTimeout:
            if args.expect_no_event:
                print(json.dumps({
                    "connected_after_cursor": cursor,
                    "duplicate_events_observed": 0,
                    "observation_seconds": args.read_timeout,
                    "classification": "OBSERVED_LIVE",
                }, sort_keys=True))
                return
            raise
    if args.expect_no_event:
        print(json.dumps({
            "connected_after_cursor": cursor,
            "duplicate_events_observed": 0,
            "classification": "OBSERVED_LIVE",
        }, sort_keys=True))
        return
    raise RuntimeError("NO_NEW_SSE_EVENT_OBSERVED")


if __name__ == "__main__":
    main()
