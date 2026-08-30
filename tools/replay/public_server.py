"""Cloud Run transport for the deterministic replay, for public judging.

This is a DEPLOYMENT transport, not a new product service. It serves two
things and nothing else:

  * the built static frontend, and
  * the same session-scoped replay API `runtime_server.py` exposes locally.

Every ordering decision still belongs to `session.py`. This file translates
HTTP into state-machine calls exactly as the local transport does, so the
canonical event contract is enforced by one implementation, not two.

It is deliberately SEPARATE from `runtime_server.py` rather than a flag on it.
The local tool asserts it can never leave loopback, which is a safety property
worth keeping literally true; a deployment transport that binds 0.0.0.0 is a
different object with a different contract, so it gets its own file.

What it cannot do, structurally:

  * no Google client library is imported, here or in `session.py`;
  * no credential, token, or service-account key is read;
  * no outbound network call of any kind is made;
  * nothing is written to disk;
  * no authoritative state exists to mutate.

Everything served is SYNTHETIC_TEST: a replay of one previously completed
run, held per visitor in memory, discarded when the instance recycles.

Run:  PORT=8080 python tools/replay/public_server.py
"""

import json
import mimetypes
import os
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import events
import session as runtime

# Cloud Run supplies PORT and requires the container to listen on it.
PORT = int(os.getenv("PORT", "8080"))
# Cloud Run terminates TLS and forwards to the container, so the listener
# must bind all interfaces. The perimeter is Cloud Run's, not the socket's.
BIND = "0.0.0.0"  # noqa: S104 - required by the Cloud Run contract

# The built frontend. Baked into the image at a fixed path by the Dockerfile.
STATIC_ROOT = pathlib.Path(
    os.getenv("FULL_SHELF_STATIC_ROOT", "/app/static")).resolve()

# Judge mode is explicit rather than inferred, so the served surface is a
# deliberate choice and is visible in the service description.
JUDGE_MODE = os.getenv("FULL_SHELF_JUDGE_MODE", "1") == "1"

# Same-origin: the frontend and the replay API are served by this one
# process, so no cross-origin grant is needed or given.
STORE = runtime.SessionStore()

# A single deterministic replay holds ~25 events and one projection cursor.
# The cap exists so an unbounded visit count cannot exhaust a 512MiB
# instance; the oldest sessions are retired first. Retiring a session only
# discards presentation state — there is nothing authoritative to lose.
MAX_SESSIONS = int(os.getenv("FULL_SHELF_MAX_SESSIONS", "400"))
_ORDER = []
_ORDER_LOCK = threading.Lock()


def _remember(session_id):
    """Track creation order and retire the oldest beyond the cap."""
    evicted = []
    with _ORDER_LOCK:
        _ORDER.append(session_id)
        while len(_ORDER) > MAX_SESSIONS:
            evicted.append(_ORDER.pop(0))
    for old in evicted:
        try:
            STORE.get(old).close()
        except runtime.ReplayError:
            pass
        with STORE._lock:  # noqa: SLF001 - same module family, no public verb
            STORE._sessions.pop(old, None)


# Static assets are immutable per build (Vite content-hashes them), so they
# may be cached hard. index.html must not be, or a redeploy would be invisible
# to a returning judge.
IMMUTABLE = "public, max-age=31536000, immutable"
NO_STORE = "no-store, must-revalidate"


class PublicHandler(BaseHTTPRequestHandler):
    server_version = "FullShelfDemoReplay/1.0"
    # Keep-alive: judges load a bundle plus a stream plus many small API
    # reads, and a new TCP connection per request is wasted latency.
    protocol_version = "HTTP/1.1"
    # The request body, read exactly once per request. See `_drain`.
    _raw_body = None

    # -- plumbing ------------------------------------------------------------

    def _security_headers(self):
        self.send_header("X-Full-Shelf-Replay-Mode", "DETERMINISTIC_TEST")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # The page needs no camera, mic, or location to replay a recorded day.
        self.send_header("Permissions-Policy",
                         "geolocation=(), microphone=(), camera=()")

    def _json(self, status, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", NO_STORE)
        self._security_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _drain(self):
        """Consume the request body, whether or not a handler wants it.

        Keep-alive makes this mandatory. On HTTP/1.1 the connection is
        reused, so a body left sitting in the socket is read as the start
        of the NEXT request line — which is exactly how `POST /sessions`
        (whose body no handler reads) turned the following request into
        `501 Unsupported method ('{"tenant_id":"test"}GET')`. Draining
        once, before routing, keeps every handler safe to ignore a body.
        """
        if self._raw_body is None:
            length = int(self.headers.get("Content-Length") or 0)
            self._raw_body = self.rfile.read(length) if length > 0 else b""
        return self._raw_body

    def _body(self):
        raw = self._drain()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise runtime.ReplayError(400, "MALFORMED_REQUEST_BODY")

    def _segments(self):
        return [p for p in urlparse(self.path).path.strip("/").split("/") if p]

    def log_message(self, fmt, *args):
        # Request logging is Cloud Run's job. Logging paths here would put
        # opaque session ids into log storage for no operational gain.
        pass

    # -- routing -------------------------------------------------------------

    def do_GET(self):
        self._raw_body = None
        try:
            self._drain()
            parts = self._segments()
            # Readiness must never touch replay state, so it is answered
            # before any session lookup and mints nothing.
            if parts == ["healthz"]:
                return self._json(200, {
                    "status": "ok",
                    "service": "full-shelf-demo-replay",
                    "mode": "DETERMINISTIC_REPLAY",
                    "judge_mode": JUDGE_MODE,
                    "classification": events.CLASSIFICATION,
                    "scenario_id": events.SCENARIO_ID,
                })
            if parts and parts[0] == "api":
                return self._route_api_get(parts)
            return self._serve_static(parts)
        except runtime.ReplayError as exc:
            self._json(exc.status, exc.body())
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        self._raw_body = None
        try:
            self._drain()
            self._route_api_post(self._segments())
        except runtime.ReplayError as exc:
            self._json(exc.status, exc.body())
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_DELETE(self):
        self._raw_body = None
        try:
            self._drain()
            parts = self._segments()
            if (len(parts) == 6 and parts[:4] == ["api", "v1", "replay", "sessions"]
                    and parts[5] == "branch"):
                return self._json(200, STORE.get(parts[4]).exit_branch())
            return self._json(404, {"detail": "NOT_A_RUNTIME_ROUTE"})
        except runtime.ReplayError as exc:
            self._json(exc.status, exc.body())

    def _route_api_get(self, parts):
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

    def _route_api_post(self, parts):
        if parts == ["api", "v1", "replay", "sessions"]:
            session = STORE.create()
            _remember(session.session_id)
            return self._json(201, {**session.state(),
                                    "history": session.history(),
                                    "feed": session.feed()})
        if len(parts) != 6 or parts[:4] != ["api", "v1", "replay", "sessions"]:
            return self._json(404, {"detail": "NOT_A_RUNTIME_ROUTE"})

        session = STORE.get(parts[4])
        action = parts[5]

        # `start` deliberately does NOT spawn a server-side autoplay thread.
        # The frontend paces the replay itself so each event can hold long
        # enough to read; a server timer would race that pacing and, at
        # concurrency 20, would burn CPU on instances with no viewer attached.
        if action == "start":
            return self._json(200, session.start())
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
            _remember(fresh.session_id)
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
        self.send_header("Cache-Control", NO_STORE)
        self.send_header("X-Accel-Buffering", "no")
        self._security_headers()
        self.end_headers()
        try:
            for block in runtime.stream(session, last_event_id=last):
                self.wfile.write(block.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    # -- static frontend -----------------------------------------------------

    def _serve_static(self, parts):
        """Serve the built SPA. Unknown paths fall back to index.html."""
        candidate = (STATIC_ROOT.joinpath(*parts) if parts else STATIC_ROOT / "index.html")
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = STATIC_ROOT / "index.html"

        # Path traversal: anything resolving outside the static root is
        # answered with the app shell rather than a file.
        if not str(resolved).startswith(str(STATIC_ROOT)) or not resolved.is_file():
            resolved = STATIC_ROOT / "index.html"

        if not resolved.is_file():
            return self._json(503, {"detail": "STATIC_BUNDLE_MISSING"})

        raw = resolved.read_bytes()
        ctype = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control",
                         NO_STORE if resolved.name == "index.html" else IMMUTABLE)
        self._security_headers()
        self.end_headers()
        self.wfile.write(raw)


def main():
    server = ThreadingHTTPServer((BIND, PORT), PublicHandler)
    server.daemon_threads = True
    print(f"DETERMINISTIC REPLAY - full-shelf-demo-replay on {BIND}:{PORT}")
    print(f"  judge_mode={JUDGE_MODE} static={STATIC_ROOT} "
          f"classification={events.CLASSIFICATION}")
    print("  no Gemini, ADK, Model Armor, KMS, Spanner, orchestrator, or ledger.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
