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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

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
  <title>Full Shelf operator bootstrap</title>
  <script src="https://accounts.google.com/gsi/client" async></script>
</head>
<body>
  <h1>Full Shelf operator bootstrap</h1>
  <p>Sign in with the Google account that will approve rev08.</p>
  <div id="google-button"></div>
  <p id="result"></p>
  <script nonce="{nonce}">
    const clientId = {client_json};
    const bootstrapNonce = {nonce_json};
    window.onload = () => {{
      google.accounts.id.initialize({{
        client_id: clientId,
        callback: async (response) => {{
          const result = await fetch('/verify', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
              credential: response.credential,
              nonce: bootstrapNonce
            }})
          }});
          document.getElementById('result').textContent = result.ok
            ? 'Verified. Return to the terminal.'
            : 'Verification failed. Check the terminal.';
        }}
      }});
      google.accounts.id.renderButton(
        document.getElementById('google-button'),
        {{theme: 'outline', size: 'large', text: 'signin_with'}}
      );
    }};
  </script>
</body>
</html>
""".encode("utf-8")


class BootstrapServer(ThreadingHTTPServer):
    client_id: str
    nonce: str


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
            "style-src 'self' https://accounts.google.com/gsi/style",
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
            if self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
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

            print("\nGoogle operator verified")
            print(f"OAuth client ID: {self.server.client_id}")
            print(f"Operator sub: {subject}")
            print(f"Operator email: {email}")
            print("Raw ID token: not retained")
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
    args = parser.parse_args()

    if not args.client_id.endswith(".apps.googleusercontent.com"):
        parser.error("--client-id must be a Google web OAuth client ID")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    server = BootstrapServer(("127.0.0.1", args.port), Handler)
    server.client_id = args.client_id
    server.nonce = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{args.port}/"
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
