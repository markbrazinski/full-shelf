"""Authenticated judge gateway — approved amendment CR-001.

A third, deliberately NON-AUTHORITATIVE Cloud Run service. Its whole job is to
stand in front of the private orchestrator for a logged-in judge:

  * serve the judge frontend;
  * verify a Cloud Identity Platform ID token on every protected call;
  * own the judge session and the single-active-run lease;
  * call the private orchestrator with this service's own workload identity;
  * emit exactly one structured `judge_login_success` per browser session.

CR-001 forbids the rest, and the code is arranged so the prohibitions are
structural rather than promised:

  * no agent logic — no ADK, no Gemini, no google-genai import;
  * no direct Spanner mutation — no Spanner client is imported at all;
  * no direct plan-ledger call — the ledger's URL is never configured here;
  * no weakening of upstream auth — the orchestrator and ledger keep their own
    verification, and this service adds a gate rather than replacing one;
  * not a source of truth — every operational value rendered comes from the
    orchestrator's projection, and nothing operational is stored here.

Judge activity is confined to the isolated judge database by the orchestrator
deployment this service points at. It never names a database itself.
"""

import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import google.auth
import google.auth.transport.requests
import google.oauth2.id_token
from google.auth import exceptions as google_auth_exceptions

PORT = int(os.getenv("PORT", "8080"))
BIND = "0.0.0.0"  # noqa: S104 - required by the Cloud Run contract

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")
# The PRIVATE orchestrator. Reached with this service's own OIDC identity.
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "").rstrip("/")
# Deliberately absent: PLAN_LEDGER_URL. CR-001 forbids calling the ledger from
# here, and the cleanest enforcement is having no address for it.

STATIC_ROOT = os.getenv("FULL_SHELF_STATIC_ROOT", "/app/static")
REVISION = os.getenv("K_REVISION", "unknown")

# Identity Platform issues judge tokens. Verified with Google's own library
# against Google's published keys — never a homemade comparison, and never a
# password check of our own.
IDENTITY_AUDIENCE = os.getenv("IDENTITY_PLATFORM_AUDIENCE", PROJECT_ID)
IDENTITY_ISSUER = f"https://securetoken.google.com/{IDENTITY_AUDIENCE}"
# Only this account may judge. An allowlist, so a stray Identity Platform
# account in the same project cannot reach operating state.
ALLOWED_JUDGE_EMAILS = frozenset(
    e.strip().lower()
    for e in os.getenv("ALLOWED_JUDGE_EMAILS", "").split(",")
    if e.strip()
)

# One live run at a time. The lease is the concurrency control CR-001 asks for.
LEASE_TTL_SECONDS = int(os.getenv("JUDGE_LEASE_TTL_SECONDS", "900"))

# Structured logging to Cloud Logging via stdout. A password or token must
# never reach here, so nothing logs a request body or an Authorization header.
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
_log = logging.getLogger("judge")


def emit(severity, event, **fields):
    """One JSON line per event; Cloud Logging parses it as structured data."""
    _log.info(json.dumps({"severity": severity, "event": event, **fields}))


class _Sessions:
    """Judge sessions and the single-active-run lease.

    Presentation and coordination state only. Nothing here is authoritative:
    losing all of it costs a judge their lease and nothing else.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}
        # (session_id, subject, expires_at) or None.
        self._lease = None

    def open(self, subject, email):
        """Return an existing session for this judge, or start a new one.

        Reusing the session per subject is what keeps a page refresh from
        emitting a second `judge_login_success`: the event is tied to the
        session's creation, not to the login call.
        """
        with self._lock:
            for sid, s in self._sessions.items():
                if s["subject"] == subject:
                    return sid, False
            sid = f"judge-{uuid.uuid4()}"
            self._sessions[sid] = {
                "subject": subject,
                "email": email,
                "created_at": time.time(),
            }
            return sid, True

    def _expire_locked(self):
        if self._lease and self._lease["expires_at"] <= time.time():
            expired = self._lease
            self._lease = None
            emit("INFO", "judge_lease_expired",
                 demo_session_id=expired["session_id"])

    def acquire(self, session_id):
        """Take the run lease, or report who holds it.

        An abandoned lease expires on its own, so a judge who closes the tab
        mid-run cannot block the next one indefinitely.
        """
        with self._lock:
            self._expire_locked()
            if self._lease and self._lease["session_id"] != session_id:
                return False, int(self._lease["expires_at"] - time.time())
            self._lease = {
                "session_id": session_id,
                "expires_at": time.time() + LEASE_TTL_SECONDS,
            }
            return True, LEASE_TTL_SECONDS

    def release(self, session_id):
        with self._lock:
            if self._lease and self._lease["session_id"] == session_id:
                self._lease = None
                return True
            return False

    def holder(self):
        with self._lock:
            self._expire_locked()
            if not self._lease:
                return None
            return {
                "session_id": self._lease["session_id"],
                "seconds_remaining": int(self._lease["expires_at"] - time.time()),
            }

    def get(self, session_id):
        with self._lock:
            return self._sessions.get(session_id)


SESSIONS = _Sessions()

_BEARER = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)


class JudgeAuthError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


def verify_judge(authorization):
    """Verify a Cloud Identity Platform ID token, server-side, every time.

    Google's own library checks the signature against Google's published keys
    and enforces the audience; the issuer and the account allowlist are checked
    here. No token or password is ever logged, and none is echoed back.
    """
    if not authorization:
        raise JudgeAuthError(401, "JUDGE_ID_TOKEN_REQUIRED")
    m = _BEARER.match(authorization.strip())
    if not m:
        raise JudgeAuthError(401, "JUDGE_ID_TOKEN_REQUIRED")

    try:
        claims = google.oauth2.id_token.verify_firebase_token(
            m.group(1),
            google.auth.transport.requests.Request(),
            audience=IDENTITY_AUDIENCE,
        )
    except (ValueError, google_auth_exceptions.GoogleAuthError) as exc:
        raise JudgeAuthError(401, "JUDGE_ID_TOKEN_INVALID") from exc

    if not claims:
        raise JudgeAuthError(401, "JUDGE_ID_TOKEN_INVALID")
    if claims.get("iss") != IDENTITY_ISSUER:
        raise JudgeAuthError(401, "JUDGE_ID_TOKEN_ISSUER_INVALID")

    email = (claims.get("email") or "").lower()
    if ALLOWED_JUDGE_EMAILS and email not in ALLOWED_JUDGE_EMAILS:
        raise JudgeAuthError(403, "JUDGE_IDENTITY_NOT_ALLOWED")
    subject = claims.get("user_id") or claims.get("sub")
    if not subject:
        raise JudgeAuthError(401, "JUDGE_ID_TOKEN_INVALID")
    return subject, email


def orchestrator_token(audience):
    """Mint this service's own OIDC token for the private orchestrator.

    The judge's token is never forwarded upstream. The orchestrator
    authenticates THIS workload, so its own gate stays exactly as strict as it
    was before this service existed.
    """
    return google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), audience)


def call_orchestrator(path, method="GET", body=None, timeout=120):
    """Service-to-service call to the private orchestrator."""
    if not ORCHESTRATOR_URL:
        raise JudgeAuthError(503, "ORCHESTRATOR_NOT_CONFIGURED")
    url = f"{ORCHESTRATOR_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {orchestrator_token(ORCHESTRATOR_URL)}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw or "{}")
        except ValueError:
            return e.code, {"detail": raw[:400]}
    except urllib.error.URLError as e:
        return 503, {"detail": f"ORCHESTRATOR_UNREACHABLE: {e.reason}"}


IMMUTABLE = "public, max-age=31536000, immutable"
NO_STORE = "no-store, must-revalidate"


class Handler(BaseHTTPRequestHandler):
    server_version = "FullShelfJudge/1.0"
    protocol_version = "HTTP/1.1"
    _raw = None

    # -- plumbing ---------------------------------------------------------

    def _sec(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy",
                         "geolocation=(), microphone=(), camera=()")

    def _json(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", NO_STORE)
        self._sec()
        self.end_headers()
        self.wfile.write(raw)

    def _drain(self):
        if self._raw is None:
            n = int(self.headers.get("Content-Length") or 0)
            self._raw = self.rfile.read(n) if n > 0 else b""
        return self._raw

    def _body(self):
        raw = self._drain()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError):
            return {}

    def _parts(self):
        return [p for p in urlparse(self.path).path.strip("/").split("/") if p]

    def log_message(self, fmt, *args):
        # Cloud Run logs requests. Logging here risks putting an Authorization
        # header or a session id into log storage for no operational gain.
        pass

    def _session_or_401(self):
        """Every protected route re-verifies the token. No trusted header."""
        subject, email = verify_judge(self.headers.get("Authorization"))
        sid = self.headers.get("X-Judge-Session") or ""
        s = SESSIONS.get(sid)
        if not s or s["subject"] != subject:
            raise JudgeAuthError(401, "JUDGE_SESSION_REQUIRED")
        return sid, subject, email

    # -- routing ----------------------------------------------------------

    def do_GET(self):
        self._raw = None
        try:
            self._drain()
            p = self._parts()
            if p in (["api", "healthz"], ["healthz"]):
                # Readiness must not require auth and must touch no state.
                return self._json(200, {
                    "status": "ok",
                    "service": "full-shelf-judge",
                    "mode": "LIVE_AUTHENTICATED",
                    "revision": REVISION,
                })
            if p == ["api", "judge", "lease"]:
                self._session_or_401()
                return self._json(200, {"lease": SESSIONS.holder()})
            if p == ["api", "judge", "projection"]:
                sid, _, _ = self._session_or_401()
                status, payload = call_orchestrator(
                    "/api/v1/projections/demo-beats")
                return self._json(status, payload)
            if p and p[0] == "api":
                return self._json(404, {"detail": "NOT_A_JUDGE_ROUTE"})
            return self._static(p)
        except JudgeAuthError as e:
            self._json(e.status, {"detail": e.code})
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        self._raw = None
        try:
            self._drain()
            p = self._parts()

            if p == ["api", "judge", "session"]:
                return self._open_session()
            if p == ["api", "judge", "lease"]:
                sid, _, _ = self._session_or_401()
                ok, secs = SESSIONS.acquire(sid)
                if not ok:
                    return self._json(409, {
                        "detail": "DEMONSTRATION_IN_PROGRESS",
                        "message": ("A demonstration is currently running. "
                                    "Please try again shortly."),
                        "seconds_remaining": secs,
                    })
                emit("INFO", "judge_lease_acquired", demo_session_id=sid,
                     ttl_seconds=secs)
                return self._json(200, {"lease": "ACQUIRED",
                                        "seconds_remaining": secs})
            if p == ["api", "judge", "lease", "release"]:
                sid, _, _ = self._session_or_401()
                released = SESSIONS.release(sid)
                if released:
                    emit("INFO", "judge_lease_released", demo_session_id=sid)
                return self._json(200, {"lease": "RELEASED" if released
                                        else "NOT_HELD"})
            if p and p[0] == "api":
                return self._json(404, {"detail": "NOT_A_JUDGE_ROUTE"})
            return self._json(404, {"detail": "NOT_A_JUDGE_ROUTE"})
        except JudgeAuthError as e:
            self._json(e.status, {"detail": e.code})
        except (BrokenPipeError, ConnectionResetError):
            return

    def _open_session(self):
        """Verify the judge, then open (or reuse) their session.

        The login event is emitted only when a session is genuinely CREATED,
        which is what keeps a refresh from producing a duplicate.
        """
        subject, email = verify_judge(self.headers.get("Authorization"))
        sid, created = SESSIONS.open(subject, email)
        if created:
            emit("NOTICE", "judge_login_success",
                 demo_session_id=sid,
                 deployed_revision=REVISION,
                 auth_provider="google_cloud_identity_platform",
                 # Deliberately no password, no token, no token fragment.
                 judge_subject=subject)
        return self._json(200, {
            "demo_session_id": sid,
            "new_session": created,
            "deployed_revision": REVISION,
        })

    # -- static frontend ---------------------------------------------------

    def _static(self, parts):
        root = os.path.realpath(STATIC_ROOT)
        candidate = os.path.realpath(os.path.join(root, *parts)) if parts else \
            os.path.join(root, "index.html")
        if not candidate.startswith(root) or not os.path.isfile(candidate):
            candidate = os.path.join(root, "index.html")
        if not os.path.isfile(candidate):
            return self._json(503, {"detail": "STATIC_BUNDLE_MISSING"})
        with open(candidate, "rb") as fh:
            raw = fh.read()
        ext = os.path.splitext(candidate)[1]
        ctype = {".html": "text/html", ".js": "text/javascript",
                 ".css": "text/css", ".svg": "image/svg+xml",
                 ".json": "application/json"}.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control",
                         NO_STORE if candidate.endswith("index.html") else IMMUTABLE)
        self._sec()
        self.end_headers()
        self.wfile.write(raw)


def main():
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    server.daemon_threads = True
    emit("NOTICE", "judge_service_started", revision=REVISION,
         orchestrator_configured=bool(ORCHESTRATOR_URL),
         allowed_judges=len(ALLOWED_JUDGE_EMAILS))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
