"""Localhost-only deterministic replay of the Full Shelf operator projection.

Purpose: let frontend development and demo rehearsal run without consuming
Gemini, ADK, Model Armor, KMS, or Spanner quota.

This is developer tooling, not a service. It lives outside apps/, is never
containerised, never referenced by cloudbuild, and refuses to bind to anything
other than the loopback interface. It calls no Google service of any kind and
serves only version-controlled fixtures generated from the production handler.

Every response is classified SYNTHETIC_TEST. If a captured real execution is
ever replayed instead, that must be classified RECORDED_LIVE, which this tool
deliberately never emits.

Run:  python tools/replay/server.py            # binds 127.0.0.1:8describe
"""

import json
import pathlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
LOOPBACK = "127.0.0.1"
PORT = 8787

INDEX = json.loads((FIXTURES / "index.json").read_text())
BEATS = {b["beat"]: b for b in INDEX["beats"]}
BY_AS_OF = {b["as_of"]: b for b in INDEX["beats"]}


def _load(beat: str) -> dict:
    return json.loads((FIXTURES / BEATS[beat]["fixture"]).read_text())


class InvalidAsOf(ValueError):
    """Malformed as_of, mirroring the production INVALID_AS_OF rejection."""


def _select(as_of: str | None, include_next_day: bool) -> dict:
    """Pick the latest beat at or before as_of, mirroring boundary semantics."""
    if as_of and as_of in BY_AS_OF:
        beat = BY_AS_OF[as_of]["beat"]
    elif as_of:
        try:
            parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            # Production returns a structured 400 INVALID_AS_OF rather than
            # crashing, and replay is only useful if it fails the same way.
            raise InvalidAsOf("INVALID_AS_OF") from exc
        eligible = [
            b for b in INDEX["beats"]
            if datetime.fromisoformat(b["as_of"]) <= parsed
        ]
        if not eligible:
            beat = INDEX["beats"][0]["beat"]
        else:
            beat = eligible[-1]["beat"]
    else:
        beat = "refusal"
    body = _load(beat)
    if not include_next_day:
        body.pop("next_day_draft", None)
    return body


class ReplayHandler(BaseHTTPRequestHandler):
    server_version = "FullShelfDeterministicReplay/1.0"

    def _json(self, status: int, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Headers",
                         "Authorization, Content-Type, Last-Event-ID")
        self.send_header("X-Full-Shelf-Replay-Mode", "DETERMINISTIC_TEST")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self._json(204, {})

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/v1/projections/demo-beats":
            as_of = (query.get("as_of") or [None])[0]
            include = (query.get("include_next_day_draft") or ["false"])[0] == "true"
            try:
                return self._json(200, _select(as_of, include))
            except InvalidAsOf:
                return self._json(400, {"detail": "INVALID_AS_OF"})
        if parsed.path == "/api/v1/projections/stream":
            return self._stream()
        if parsed.path == "/__replay/beats":
            return self._json(200, INDEX)
        return self._json(404, {"detail": "NOT_A_REPLAYED_ROUTE"})

    def _stream(self):
        """Emit committed receipts in real commit order, once, then idle."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("X-Full-Shelf-Replay-Mode", "DETERMINISTIC_TEST")
        self.end_headers()
        final = _load("refusal")
        receipts = final.get("__replay_receipts") or []
        for event in receipts:
            payload = {
                "event_id": event["event_id"],
                "projection_type": "SPANNER_COMMITTED_RECEIPT",
                "classification": "SYNTHETIC_TEST",
                "data": event,
                "emitted_at": datetime.now(timezone.utc).isoformat(),
            }
            block = (f"id: {event['event_id']}\n"
                     f"event: projection_update\n"
                     f"data: {json.dumps(payload)}\n\n")
            self.wfile.write(block.encode("utf-8"))
            self.wfile.flush()

    def log_message(self, fmt, *args):
        pass


def main():
    server = ThreadingHTTPServer((LOOPBACK, PORT), ReplayHandler)
    host, port = server.server_address[:2]
    assert host == LOOPBACK, "replay server must never leave loopback"
    print(f"DETERMINISTIC TEST MODE - replay on http://{LOOPBACK}:{port}")
    print("  fixtures only. no Gemini, ADK, Model Armor, KMS, Spanner, or ledger.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
