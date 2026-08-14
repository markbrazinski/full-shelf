#!/usr/bin/env python3
"""Verify one GIS login locally and reveal only the stable operator identity.

The raw Google ID token is held in memory only long enough for verification. It
is never logged, printed, or written to disk.
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


GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
MAX_REQUEST_BYTES = 16_384


def _page(client_id: str, nonce: str) -> bytes:
    client_json = json.dumps(client_id)
    nonce_json = json.dumps(nonce)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Approve plan revision · Full Shelf</title>
  <style nonce="{nonce}">
    :root {{
      font-family: Inter, ui-sans-serif, system-ui, -apple-system,
        BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #f8fafc;
      background: #07111f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
      padding: 32px 20px;
      background:
        radial-gradient(circle at 18% 12%, rgba(34, 197, 94, .13), transparent 34%),
        radial-gradient(circle at 84% 88%, rgba(59, 130, 246, .10), transparent 38%),
        #07111f;
    }}
    main {{ width: min(100%, 480px); }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin: 0 0 18px;
      color: #cbd5e1;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    .brand-mark {{
      width: 36px;
      height: 36px;
      display: grid;
      place-items: center;
      border: 1px solid rgba(74, 222, 128, .32);
      border-radius: 11px;
      background: rgba(34, 197, 94, .12);
      color: #86efac;
      font-size: 12px;
      letter-spacing: -.02em;
    }}
    .card {{
      overflow: hidden;
      border: 1px solid #243244;
      border-radius: 22px;
      background: rgba(15, 23, 42, .96);
      box-shadow: 0 28px 80px rgba(0, 0, 0, .38);
    }}
    .card-accent {{ height: 4px; background: #22c55e; }}
    .content {{ padding: 32px; }}
    .eyebrow {{
      margin: 0 0 10px;
      color: #86efac;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .11em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(28px, 6vw, 38px);
      line-height: 1.08;
      letter-spacing: -.035em;
    }}
    .lede {{
      margin: 16px 0 0;
      color: #aebdce;
      font-size: 15px;
      line-height: 1.6;
    }}
    .approval {{
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      gap: 10px;
      margin: 26px 0;
      padding: 15px 16px;
      border: 1px solid #2b3a4e;
      border-radius: 14px;
      background: #0b1525;
    }}
    .revision {{ font-size: 14px; font-weight: 750; }}
    .revision:last-child {{ text-align: right; color: #86efac; }}
    .arrow {{ color: #64748b; }}
    .google-shell {{
      width: 100%;
      min-height: 46px;
      display: grid;
      place-items: center;
      overflow: hidden;
      border-radius: 8px;
    }}
    #google-button {{
      width: 100%;
      min-height: 44px;
      display: grid;
      place-items: center;
      overflow: hidden;
    }}
    #google-button > div,
    #google-button iframe {{
      max-width: 100% !important;
      max-height: 44px !important;
    }}
    #google-button img,
    #google-button svg {{
      max-width: 24px !important;
      max-height: 24px !important;
    }}
    .status {{
      min-height: 22px;
      margin: 16px 0 0;
      color: #94a3b8;
      font-size: 13px;
      line-height: 1.5;
      text-align: center;
    }}
    .status[data-state="success"] {{ color: #86efac; }}
    .status[data-state="error"] {{ color: #fca5a5; }}
    .security {{
      display: flex;
      gap: 10px;
      align-items: flex-start;
      margin: 24px 0 0;
      padding-top: 20px;
      border-top: 1px solid #243244;
      color: #7f91a7;
      font-size: 12px;
      line-height: 1.55;
    }}
    .security-icon {{ color: #86efac; font-size: 15px; line-height: 1.2; }}
    @media (max-width: 520px) {{
      .content {{ padding: 26px 22px; }}
    }}
  </style>
  <script src="https://accounts.google.com/gsi/client" async></script>
</head>
<body>
  <main>
    <div class="brand"><span class="brand-mark">FS</span> Full Shelf</div>
    <section class="card" aria-labelledby="page-title">
      <div class="card-accent"></div>
      <div class="content">
        <p class="eyebrow">Governed operator action</p>
        <h1 id="page-title">Approve plan revision</h1>
        <p class="lede">
          Verify your authorized Google identity to bind and activate this
          repair through the deployed approval boundary.
        </p>
        <div class="approval" aria-label="Plan revision rev07 to rev08">
          <span class="revision">rev07</span>
          <span class="arrow" aria-hidden="true">→</span>
          <span class="revision">rev08</span>
        </div>
        <div class="google-shell">
          <div id="google-button"></div>
        </div>
        <p id="result" class="status" role="status" aria-live="polite">
          Select the allowlisted operator account to continue.
        </p>
        <div class="security">
          <span class="security-icon" aria-hidden="true">●</span>
          <span>Your Google credential is verified in memory and is never
          printed or written to disk.</span>
        </div>
      </div>
    </section>
  </main>
  <script nonce="{nonce}">
    const clientId = {client_json};
    const bootstrapNonce = {nonce_json};
    window.onload = () => {{
      google.accounts.id.initialize({{
        client_id: clientId,
        callback: async (response) => {{
          const status = document.getElementById('result');
          status.dataset.state = 'pending';
          status.textContent = 'Verifying identity and submitting approval…';
          const result = await fetch('/verify', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
              credential: response.credential,
              nonce: bootstrapNonce
            }})
          }});
          status.dataset.state = result.ok ? 'success' : 'error';
          status.textContent = result.ok
            ? 'Approval recorded. You can return to the terminal.'
            : 'Approval could not be completed. Check the terminal.';
        }}
      }});
      google.accounts.id.renderButton(
        document.getElementById('google-button'),
        {{
          theme: 'filled_black',
          size: 'large',
          text: 'continue_with',
          shape: 'rectangular',
          width: 360
        }}
      );
    }};
  </script>
</body>
</html>
""".encode("utf-8")


class BootstrapServer(ThreadingHTTPServer):
    client_id: str
    nonce: str
    approval_payload: dict[str, Any] | None
    orchestrator_url: str | None


class Handler(BaseHTTPRequestHandler):
    server: BootstrapServer

    def log_message(self, _format: str, *args: Any) -> None:
        # BaseHTTPRequestHandler logs request paths by default. Silence all HTTP
        # logging so a future route change cannot accidentally expose a token.
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
            f"script-src 'self' 'nonce-{self.server.nonce}' "
            "https://accounts.google.com/gsi/client; "
            "frame-src https://accounts.google.com/gsi/; "
            "connect-src 'self' https://accounts.google.com/gsi/; "
            f"style-src 'self' 'nonce-{self.server.nonce}' "
            "https://accounts.google.com/gsi/style; "
            "img-src 'self' data: https://accounts.google.com "
            "https://*.gstatic.com",
        )
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/":
            self._headers(404, "text/plain; charset=utf-8")
            self.wfile.write(b"Not found")
            return
        body = _page(self.server.client_id, self.server.nonce)
        self._headers(200, "text/html; charset=utf-8")
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/verify":
            self._headers(404, "application/json")
            self.wfile.write(b'{"ok":false}')
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("invalid request size")
            if self.headers.get("Origin") not in {
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            }:
                raise ValueError("invalid origin")
            payload = json.loads(self.rfile.read(length))
            credential = payload.get("credential")
            supplied_nonce = payload.get("nonce")
            if not isinstance(credential, str) or not credential:
                raise ValueError("missing credential")
            if not isinstance(supplied_nonce, str) or not hmac.compare_digest(
                supplied_nonce, self.server.nonce
            ):
                raise ValueError("invalid bootstrap nonce")

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
            subject = claims.get("sub")
            email = claims.get("email")
            if not isinstance(subject, str) or not subject:
                raise ValueError("missing subject")
            if not isinstance(email, str) or not email:
                raise ValueError("missing email")

            approval_result = None
            if self.server.approval_payload is not None:
                response = httpx.post(
                    f"{self.server.orchestrator_url.rstrip('/')}/api/v1/orchestrator/approvals/approve-and-activate",
                    headers={"Authorization": f"Bearer {credential}"},
                    json=self.server.approval_payload,
                    timeout=60,
                )
                response.raise_for_status()
                result = response.json()
                approval_result = {
                    "approval_receipt_id": result["approval_receipt"]["receipt_id"],
                    "activation_receipt_id": result["activation_receipt"]["receipt_id"],
                    "plan_diff_hash": result["plan_diff_hash"],
                    "kms_key_version": result["kms_key_version"],
                }

            print("\nGoogle operator verified")
            print(f"OAuth client ID: {self.server.client_id}")
            print(f"Operator sub: {subject}")
            print(f"Operator email: {email}")
            print("Raw ID token: not retained")
            if approval_result:
                print("Deployed approval committed")
                print(json.dumps(approval_result, sort_keys=True))
            self._headers(200, "application/json")
            self.wfile.write(b'{"ok":true}')
        except Exception as exc:
            print(f"\nVerification failed: {type(exc).__name__}")
            self._headers(401, "application/json")
            self.wfile.write(b'{"ok":false}')
        finally:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap the real Full Shelf Google operator identity."
    )
    parser.add_argument(
        "--client-id",
        required=True,
        help="Google Auth Platform Web application client ID",
    )
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--approval-payload",
        type=Path,
        help="Optional JSON payload to submit to the deployed orchestrator in memory",
    )
    parser.add_argument(
        "--approval-fixture",
        choices=["canonical", "altered"],
        help="Build a fresh approval payload from an isolated audit fixture",
    )
    parser.add_argument(
        "--orchestrator-url",
        default="https://full-shelf-orchestrator-620464070103.us-central1.run.app",
    )
    args = parser.parse_args()

    if not args.client_id.endswith(".apps.googleusercontent.com"):
        parser.error("--client-id must be a Google web OAuth client ID")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    server = BootstrapServer(("127.0.0.1", args.port), Handler)
    server.client_id = args.client_id
    server.nonce = secrets.token_urlsafe(32)
    if args.approval_payload and args.approval_fixture:
        parser.error("choose only one of --approval-payload or --approval-fixture")
    if args.approval_fixture:
        fixture_name = (
            "audit_canonical_shaped.json"
            if args.approval_fixture == "canonical"
            else "audit_altered.json"
        )
        fixture = json.loads(
            (Path(__file__).resolve().parents[1] / "test-fixtures" / fixture_name)
            .read_text()
        )
        approval = fixture["approval"]
        suffix = args.approval_fixture.upper()
        server.approval_payload = {
            "command_id": f"CMD-DELTA-{suffix}",
            "idempotency_key": f"delta:{args.approval_fixture}:human-approval",
            "tenant_id": fixture["tenant_id"],
            "incident_id": approval["incident_id"],
            "plan_id": fixture["operating_plan"]["plan_id"],
            "source_revision": "rev07",
            "proposed_revision": "rev08",
            "approval_id": approval["approval_id"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=20))
            .isoformat().replace("+00:00", "Z"),
            "plan_diff": approval["plan_diff"],
        }
    else:
        server.approval_payload = (
            json.loads(args.approval_payload.read_text()) if args.approval_payload else None
        )
    server.orchestrator_url = args.orchestrator_url if server.approval_payload else None
    url = f"http://localhost:{args.port}/"
    print(f"Opening {url}")
    print("The server will stop after one verification attempt.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCancelled")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
