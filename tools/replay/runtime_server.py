"""Localhost-only HTTP transport for the deterministic runtime controller.

Developer tooling, not a service. It lives outside apps/, is never containerised,
never referenced by any cloudbuild file, and refuses to bind anywhere but the
loopback interface. It calls no Google service of any kind: no Gemini, no ADK,
no Model Armor, no KMS, no Spanner, no ledger.

Ordering is enforced by the session state machine, never by this transport. The
server only translates HTTP into state-machine calls and refusals into statuses.

Every response is SYNTHETIC_TEST. Approval here is synthetic and disclosed as
such; it claims no real authentication, KMS signature, or human identity.

Run:  python tools/replay/runtime_server.py     # binds 127.0.0.1:8788
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import events
import session as runtime

LOOPBACK = "127.0.0.1"
PORT = int(os.getenv("FULL_SHELF_RUNTIME_PORT", "8788"))
WEB_ORIGIN = os.getenv("FULL_SHELF_WEB_ORIGIN", "http://127.0.0.1:5173")

# `localhost` and `127.0.0.1` are the SAME dev server but different origins to
# the browser, and a page served from one could not call an API allowlisted for
# the other: every request failed CORS and the app rendered its connection
# error. Both loopback spellings are allowed, plus the IPv6 literal, since
# macOS browsers may resolve localhost to ::1. Still an explicit allowlist —
# a loopback dev origin only, never a wildcard.
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
ALLOWED_ORIGINS = frozenset(
    [WEB_ORIGIN] + [f"http://{host}:{port}" for host in _LOOPBACK_HOSTS
                    for port in ("5173", "5174")]
)

# Compressed wall-clock pacing. Presentation only: it never changes scenario
# time, which advances solely when the next accepted event commits.
DEFAULT_INTERVAL_MS = int(os.getenv("FULL_SHELF_RUNTIME_INTERVAL_MS", "900"))

STORE = runtime.SessionStore()


def _autoplay(session, interval_ms):
    """Drive a session forward until it completes, is paused, or is closed.

    The thread survives the human gate: on reaching event 9 the session flips to
    PAUSED_HUMAN_GATE and this loop waits on the condition until approve() sets
    it back to PLAYING, rather than exiting and stranding the session at 10.
    """
    interval = max(interval_ms, 0) / 1000.0
    while True:
        with session.cond:
            if session.closed or session.mode in (runtime.PAUSED, runtime.COMPLETE):
                return
            if session.mode == runtime.PAUSED_HUMAN_GATE:
                # Approval is the only thing that can move this forward.
                session.cond.wait(timeout=interval)
                continue
            if session.mode != runtime.PLAYING:
                return
            # Sleeping on the condition keeps pause and reset responsive.
            session.cond.wait(timeout=interval)
            if session.closed or session.mode in (runtime.PAUSED, runtime.COMPLETE):
                return
        if session.autoplay_step() is None:
            with session.cond:
                # Stop only when genuinely finished or paused by an operator.
                if session.mode != runtime.PAUSED_HUMAN_GATE:
                    return


class RuntimeHandler(BaseHTTPRequestHandler):
    server_version = "FullShelfGoldenRuntime/1.0"

    # -- plumbing ------------------------------------------------------------

    def _headers(self):
        # Echo the caller's own origin when it is an allowlisted loopback
        # dev origin; the browser rejects a response whose allow-origin
        # does not match the request origin exactly.
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin",
                         origin if origin in ALLOWED_ORIGINS else WEB_ORIGIN)
        self.send_header("Access-Control-Allow-Headers",
                         "Authorization, Content-Type, Last-Event-ID")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, DELETE, OPTIONS")
        self.send_header("X-Full-Shelf-Replay-Mode", "DETERMINISTIC_TEST")

    def _json(self, status, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._headers()
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise runtime.ReplayError(400, "MALFORMED_REQUEST_BODY")

    def _segments(self):
        return [p for p in urlparse(self.path).path.strip("/").split("/") if p]

    def log_message(self, fmt, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self._headers()
        self.end_headers()

    # -- routing -------------------------------------------------------------

    def do_GET(self):
        try:
            self._route_get(self._segments())
        except runtime.ReplayError as exc:
            self._json(exc.status, exc.body())

    def do_POST(self):
        try:
            self._route_post(self._segments())
        except runtime.ReplayError as exc:
            self._json(exc.status, exc.body())

    def do_DELETE(self):
        try:
            parts = self._segments()
            if len(parts) == 6 and parts[:3] == ["api", "v1", "replay"] \
                    and parts[3] == "sessions" and parts[5] == "branch":
                session = STORE.get(parts[4])
                return self._json(200, session.exit_branch())
            return self._json(404, {"detail": "NOT_A_RUNTIME_ROUTE"})
        except runtime.ReplayError as exc:
            self._json(exc.status, exc.body())

    def _route_get(self, parts):
        if parts == ["api", "v1", "replay", "events"]:
            return self._json(200, {
                "scenario_id": events.SCENARIO_ID,
                "classification": events.CLASSIFICATION,
                "initial_cursor": events.INITIAL_CURSOR,
                "human_gate": events.HUMAN_GATE_SEQUENCE,
                "events": [
                    {"sequence": e.sequence, "event_id": e.event_id,
                     "effective_at": e.effective_at.isoformat(),
                     "trigger_class": e.trigger_class}
                    for e in events.CANONICAL_EVENTS
                ],
            })
        if len(parts) < 5 or parts[:4] != ["api", "v1", "replay", "sessions"]:
            return self._json(404, {"detail": "NOT_A_RUNTIME_ROUTE"})

        session = STORE.get(parts[4])
        tail = parts[5:]
        if not tail:
            return self._json(200, {**session.state(),
                                    "history": session.history(),
                                    "feed": session.feed()})
        if tail == ["projection"]:
            return self._json(200, session.projection())
        if tail == ["stream"]:
            return self._stream(session)
        if tail == ["branch"]:
            return self._json(200, {"branch": session.branch,
                                    "events": session.branch_feed()})
        return self._json(404, {"detail": "NOT_A_RUNTIME_ROUTE"})

    def _route_post(self, parts):
        if parts == ["api", "v1", "replay", "sessions"]:
            session = STORE.create()
            return self._json(201, {**session.state(),
                                    "history": session.history(),
                                    "feed": session.feed()})
        if len(parts) != 6 or parts[:4] != ["api", "v1", "replay", "sessions"]:
            return self._json(404, {"detail": "NOT_A_RUNTIME_ROUTE"})

        session = STORE.get(parts[4])
        action = parts[5]

        if action == "start":
            body = self._body()
            interval = int(body.get("interval_ms") or DEFAULT_INTERVAL_MS)
            state = session.start()
            threading.Thread(target=_autoplay, args=(session, interval),
                             daemon=True).start()
            return self._json(200, state)
        if action == "pause":
            return self._json(200, session.pause())
        if action == "advance":
            return self._json(200, session.advance())
        if action == "approve":
            return self._json(200, session.approve(self._body()))
        if action == "branch":
            return self._json(200, session.enter_branch(
                (self._body() or {}).get("proof")))
        if action == "reset":
            fresh = STORE.reset(parts[4])
            return self._json(201, {**fresh.state(),
                                    "history": fresh.history(),
                                    "feed": fresh.feed()})
        return self._json(404, {"detail": "NOT_A_RUNTIME_ROUTE"})

    # -- SSE -----------------------------------------------------------------

    def _stream(self, session):
        last = self.headers.get("Last-Event-ID")
        try:
            runtime.parse_last_event_id(last)
        except runtime.ReplayError as exc:
            return self._json(exc.status, exc.body())

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self._headers()
        self.end_headers()
        try:
            for block in runtime.stream(session, last_event_id=last):
                self.wfile.write(block.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def main():
    server = ThreadingHTTPServer((LOOPBACK, PORT), RuntimeHandler)
    host, port = server.server_address[:2]
    assert host == LOOPBACK, "runtime controller must never leave loopback"
    print(f"DETERMINISTIC TEST MODE - golden runtime on http://{LOOPBACK}:{port}")
    print("  synthetic session replay. no Gemini, ADK, Model Armor, KMS, "
          "Spanner, or ledger.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
