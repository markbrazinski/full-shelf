#!/usr/bin/env python3
"""Run one bounded, memory-only Full Shelf operator audit session.

The Google ID token never leaves process memory, is never printed or logged,
and can only authorize the fixed approval, projection, and SSE operations below.
"""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_URL = (
    "https://full-shelf-orchestrator-620464070103.us-central1.run.app"
)
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
MAX_REQUEST_BYTES = 4_096


def _page(client_id: str, state: str, gis_nonce: str) -> bytes:
    client_json = json.dumps(client_id)
    state_json = json.dumps(state)
    nonce_json = json.dumps(gis_nonce)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Full Shelf operator audit session</title>
  <style nonce="{state}">
    :root {{ font-family: Inter, system-ui, sans-serif; color: #f8fafc; background: #07111f; }}
    body {{ min-height: 100vh; margin: 0; display: grid; place-items: center; padding: 24px; }}
    main {{ width: min(100%, 620px); padding: 30px; border: 1px solid #294057;
      border-radius: 20px; background: #0f172a; box-shadow: 0 24px 70px #0008; }}
    h1 {{ margin-top: 0; }} p {{ color: #b9c7d8; line-height: 1.55; }}
    #controls {{ display: none; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 22px; }}
    button, a {{ min-height: 42px; padding: 10px 14px; border: 1px solid #3c526a;
      border-radius: 9px; background: #142338; color: #f8fafc; font: inherit; cursor: pointer;
      text-align: center; text-decoration: none; }}
    button:hover, a:hover {{ border-color: #86efac; }}
    #shutdown {{ border-color: #7f1d1d; }} #status {{ min-height: 48px; white-space: pre-wrap; }}
  </style>
  <script src="https://accounts.google.com/gsi/client" async></script>
</head>
<body>
  <main>
    <h1>Full Shelf audit session</h1>
    <p>One Google login authorizes only the fixed Full Shelf operations shown here.
      The credential remains in this loopback process and is discarded on shutdown.</p>
    <div id="google-button"></div>
    <div id="controls">
      <button data-op="canonical">Submit canonical approval</button>
      <button data-op="altered">Submit altered approval</button>
      <button id="projection">Fetch authoritative projection</button>
      <a href="/session/sse" target="_blank" rel="noreferrer">Open authenticated SSE</a>
      <button id="shutdown">Shut down session</button>
    </div>
    <p id="status" role="status">Select the allowlisted Google account.</p>
  </main>
  <script nonce="{state}">
    const sessionState = {state_json};
    const status = document.getElementById('status');
    const sessionHeaders = {{'X-Full-Shelf-Session-State': sessionState}};
    const show = value => {{ status.textContent = value; }};
    window.onload = () => {{
      google.accounts.id.initialize({{
        client_id: {client_json},
        nonce: {nonce_json},
        callback: async response => {{
          show('Verifying signed Google identity…');
          const result = await fetch('/verify', {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{credential: response.credential, state: sessionState}})
          }});
          if (!result.ok) {{ show('Identity verification failed.'); return; }}
          document.getElementById('google-button').style.display = 'none';
          document.getElementById('controls').style.display = 'grid';
          show('Authenticated. The token is held only in process memory.');
        }}
      }});
      google.accounts.id.renderButton(document.getElementById('google-button'),
        {{theme: 'filled_black', size: 'large', text: 'continue_with', width: 360}});
    }};
    document.querySelectorAll('[data-op]').forEach(button => button.onclick = async () => {{
      show(`Submitting ${{button.dataset.op}} approval…`);
      const response = await fetch('/session/approval', {{method: 'POST',
        headers: {{...sessionHeaders, 'Content-Type': 'application/json'}},
        body: JSON.stringify({{fixture: button.dataset.op}})}});
      show(await response.text());
    }});
    document.getElementById('projection').onclick = async () => {{
      show('Reading authoritative projection…');
      const response = await fetch('/session/projection');
      show(await response.text());
    }};
    document.getElementById('shutdown').onclick = async () => {{
      await fetch('/session/shutdown', {{method: 'POST', headers: sessionHeaders}});
      show('Session shut down; in-memory credential discarded.');
      document.getElementById('controls').style.display = 'none';
    }};
  </script>
</body>
</html>
""".encode()


class AuditSessionServer(ThreadingHTTPServer):
    client_id: str
    allowed_subject: str
    expected_email: str
    state: str
    gis_nonce: str
    approval_payloads: dict[str, dict[str, Any]]
    credential: str | None = None
    credential_expires_at: datetime | None = None
    credential_lock: threading.Lock

    def clear_credential(self) -> None:
        with self.credential_lock:
            self.credential = None
            self.credential_expires_at = None

    def active_credential(self) -> str:
        with self.credential_lock:
            if (
                self.credential is None
                or self.credential_expires_at is None
                or self.credential_expires_at <= datetime.now(timezone.utc)
            ):
                self.credential = None
                self.credential_expires_at = None
                raise PermissionError("operator session is not authenticated or has expired")
            return self.credential


class Handler(BaseHTTPRequestHandler):
    server: AuditSessionServer

    def log_message(self, _format: str, *args: Any) -> None:
        return

    def _headers(self, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{self.server.state}' https://accounts.google.com/gsi/client; "
            "frame-src https://accounts.google.com/gsi/; connect-src 'self' https://accounts.google.com/gsi/; "
            f"style-src 'self' 'nonce-{self.server.state}'; img-src 'self' data: https://*.gstatic.com",
        )
        self.end_headers()

    def _origin_is_loopback(self) -> bool:
        return self.headers.get("Origin") in {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }

    def _session_state_is_valid(self) -> bool:
        supplied = self.headers.get("X-Full-Shelf-Session-State", "")
        return bool(supplied) and hmac.compare_digest(supplied, self.server.state)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("invalid request size")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            body = _page(self.server.client_id, self.server.state, self.server.gis_nonce)
            self._headers(200, "text/html; charset=utf-8")
            self.wfile.write(body)
            return
        if self.path == "/session/projection":
            self._proxy_projection()
            return
        if self.path == "/session/sse":
            self._proxy_sse()
            return
        self._headers(404, "application/json")
        self.wfile.write(b'{"detail":"NOT_FOUND"}')

    def do_POST(self) -> None:  # noqa: N802
        if not self._origin_is_loopback():
            self._headers(403, "application/json")
            self.wfile.write(b'{"detail":"LOOPBACK_ORIGIN_REQUIRED"}')
            return
        if self.path == "/verify":
            self._verify_login()
            return
        if not self._session_state_is_valid():
            self._headers(403, "application/json")
            self.wfile.write(b'{"detail":"SESSION_STATE_INVALID"}')
            return
        if self.path == "/session/approval":
            self._submit_approval()
            return
        if self.path == "/session/shutdown":
            self.server.clear_credential()
            self._headers(200, "application/json")
            self.wfile.write(b'{"ok":true}')
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._headers(404, "application/json")
        self.wfile.write(b'{"detail":"NOT_FOUND"}')

    def _verify_login(self) -> None:
        try:
            payload = self._read_json()
            credential = payload.get("credential")
            supplied_state = payload.get("state")
            if not isinstance(credential, str) or not credential:
                raise ValueError("missing credential")
            if not isinstance(supplied_state, str) or not hmac.compare_digest(
                supplied_state, self.server.state
            ):
                raise ValueError("invalid GIS state")
            claims = id_token.verify_oauth2_token(
                credential,
                GoogleAuthRequest(),
                audience=self.server.client_id,
                clock_skew_in_seconds=0,
            )
            if claims.get("iss") not in GOOGLE_ISSUERS:
                raise ValueError("invalid issuer")
            if claims.get("email_verified") is not True:
                raise ValueError("email is not verified")
            if claims.get("nonce") != self.server.gis_nonce:
                raise ValueError("invalid GIS nonce")
            subject = claims.get("sub")
            email = claims.get("email")
            expires_at = claims.get("exp")
            if not isinstance(subject, str) or not subject:
                raise ValueError("missing subject")
            if not isinstance(email, str) or not email:
                raise ValueError("missing email")
            if subject != self.server.allowed_subject:
                raise PermissionError("operator subject is not allowlisted")
            if email.lower() != self.server.expected_email.lower():
                raise PermissionError("operator email does not match supporting evidence")
            if not isinstance(expires_at, (int, float)):
                raise ValueError("missing expiry")
            expiry = datetime.fromtimestamp(expires_at, tz=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                raise ValueError("expired credential")
            with self.server.credential_lock:
                self.server.credential = credential
                self.server.credential_expires_at = expiry
            self._headers(200, "application/json")
            self.wfile.write(b'{"ok":true}')
        except Exception:
            self.server.clear_credential()
            self._headers(401, "application/json")
            self.wfile.write(b'{"ok":false}')

    def _submit_approval(self) -> None:
        try:
            credential = self.server.active_credential()
            payload = self._read_json()
            if set(payload) != {"fixture"} or payload["fixture"] not in {"canonical", "altered"}:
                raise ValueError("fixed fixture required")
            approval_payload = dict(self.server.approval_payloads[payload["fixture"]])
            approval_payload["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(minutes=20)
            ).isoformat().replace("+00:00", "Z")
            response = httpx.post(
                f"{ORCHESTRATOR_URL}/api/v1/orchestrator/approvals/approve-and-activate",
                headers={"Authorization": f"Bearer {credential}"},
                json=approval_payload,
                timeout=60,
            )
            body = response.content
            self._headers(response.status_code, "application/json")
            self.wfile.write(body)
        except PermissionError:
            self._headers(401, "application/json")
            self.wfile.write(b'{"detail":"OPERATOR_SESSION_REQUIRED"}')
        except Exception:
            self._headers(400, "application/json")
            self.wfile.write(b'{"detail":"FIXED_APPROVAL_OPERATION_FAILED"}')

    def _proxy_projection(self) -> None:
        try:
            credential = self.server.active_credential()
            response = httpx.get(
                f"{ORCHESTRATOR_URL}/api/v1/projections/demo-beats",
                headers={"Authorization": f"Bearer {credential}"},
                timeout=30,
            )
            self._headers(response.status_code, "application/json")
            self.wfile.write(response.content)
        except PermissionError:
            self._headers(401, "application/json")
            self.wfile.write(b'{"detail":"OPERATOR_SESSION_REQUIRED"}')
        except Exception:
            self._headers(502, "application/json")
            self.wfile.write(b'{"detail":"PROJECTION_OPERATION_FAILED"}')

    def _proxy_sse(self) -> None:
        try:
            credential = self.server.active_credential()
            headers = {"Authorization": f"Bearer {credential}"}
            cursor = self.headers.get("Last-Event-ID", "").strip()
            if cursor:
                headers["Last-Event-ID"] = cursor
            with httpx.stream(
                "GET",
                f"{ORCHESTRATOR_URL}/api/v1/projections/stream",
                headers=headers,
                timeout=httpx.Timeout(90, read=90),
            ) as response:
                self._headers(response.status_code, "text/event-stream")
                if response.status_code != 200:
                    self.wfile.write(response.read())
                    return
                for chunk in response.iter_bytes():
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        except PermissionError:
            self._headers(401, "application/json")
            self.wfile.write(b'{"detail":"OPERATOR_SESSION_REQUIRED"}')
        except Exception:
            return


def _approval_payloads(tenant_id: str, operating_day: str) -> dict[str, dict[str, Any]]:
    payloads = {}
    for fixture_key, fixture_name in {
        "canonical": "audit_canonical_shaped.json",
        "altered": "audit_altered.json",
    }.items():
        fixture = json.loads((ROOT / "test-fixtures" / fixture_name).read_text())
        approval = fixture["approval"]
        suffix = fixture_key.upper()
        payloads[fixture_key] = {
            "command_id": f"CMD-DELTA-{suffix}",
            "idempotency_key": f"delta:{fixture_key}:human-approval",
            "tenant_id": tenant_id,
            "operating_day": operating_day,
            "incident_id": approval["incident_id"],
            "plan_id": fixture["operating_plan"]["plan_id"],
            "source_revision": "rev07",
            "proposed_revision": "rev08",
            "approval_id": approval["approval_id"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=20))
            .isoformat().replace("+00:00", "Z"),
            "plan_diff": approval["plan_diff"],
        }
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded Full Shelf operator audit session.")
    parser.add_argument("--client-id", required=True, help="Google web OAuth client ID")
    parser.add_argument("--allowed-subject", required=True, help="Exact allowlisted Mark subject")
    parser.add_argument("--expected-email", required=True, help="Expected verified Mark email")
    parser.add_argument("--tenant-id", required=True, help="Fixed isolated audit authority tenant")
    parser.add_argument("--operating-day", required=True, help="Fixed YYYY-MM-DD approval day")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if not args.client_id.endswith(".apps.googleusercontent.com"):
        parser.error("--client-id must be a Google web OAuth client ID")
    try:
        datetime.fromisoformat(args.operating_day)
    except ValueError:
        parser.error("--operating-day must be YYYY-MM-DD")
    if not args.tenant_id.startswith("audit-"):
        parser.error("--tenant-id must be an isolated audit tenant")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    server = AuditSessionServer(("127.0.0.1", args.port), Handler)
    server.client_id = args.client_id
    server.allowed_subject = args.allowed_subject
    server.expected_email = args.expected_email
    server.state = secrets.token_urlsafe(32)
    server.gis_nonce = secrets.token_urlsafe(32)
    server.credential_lock = threading.Lock()
    server.approval_payloads = _approval_payloads(args.tenant_id, args.operating_day)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Opening bounded loopback audit session at {url}")
    print("Use the explicit Shut down session control when the audit operations finish.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSession cancelled")
    finally:
        server.clear_credential()
        server.server_close()
        print("In-memory operator credential discarded; loopback listener closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
