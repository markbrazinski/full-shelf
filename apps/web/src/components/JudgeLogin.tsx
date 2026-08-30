// =====================================================================
// Judge sign-in — Cloud Identity Platform
// ---------------------------------------------------------------------
// The gate in front of the demonstration. It never compares a password
// itself: the credential goes to Identity Platform, which verifies it
// against Google-managed SCRYPT hashes and returns a signed ID token.
// The server then verifies that token on every protected request, so
// hiding this screen would not grant access on its own.
//
// The token is held in memory for the tab's lifetime only. Nothing is
// written to localStorage: a shared or borrowed browser must not stay
// signed in after the tab closes.
// =====================================================================

import { useState } from "react";
import { css } from "../styles/css";

const SIGN_IN_ENDPOINT =
  "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword";

export interface JudgeSession {
  idToken: string;
  email: string;
}

/**
 * Exchange credentials for an Identity Platform ID token.
 *
 * Every failure is reported with ONE message. Identity Platform
 * distinguishes "no such account" from "wrong password", and passing
 * that through would tell an attacker which half they got right.
 */
async function signIn(
  apiKey: string,
  email: string,
  password: string,
): Promise<JudgeSession> {
  const res = await fetch(`${SIGN_IN_ENDPOINT}?key=${encodeURIComponent(apiKey)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, returnSecureToken: true }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || !body?.idToken) {
    throw new Error("Those credentials were not recognised.");
  }
  return { idToken: body.idToken as string, email: body.email as string };
}

export function JudgeLogin({
  apiKey,
  onAuthenticated,
}: {
  apiKey: string;
  onAuthenticated: (session: JudgeSession) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      // Judges are given the username "Judge", not an email address. The
      // provider needs an email-shaped identifier, so a bare username is
      // completed to the account's domain here. Anything already
      // containing "@" is passed through untouched.
      const identifier = username.includes("@")
        ? username.trim()
        : `${username.trim().toLowerCase()}@fullshelf.demo`;
      onAuthenticated(await signIn(apiKey, identifier, password));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="judge-login"
      style={css(
        "height:100vh;display:flex;align-items:center;justify-content:center;" +
          "background:#12292f;padding:24px",
      )}
    >
      <form
        onSubmit={submit}
        style={css(
          "width:100%;max-width:392px;background:#eef0ea;border-radius:14px;" +
            "padding:32px 30px 28px;display:flex;flex-direction:column;gap:16px",
        )}
      >
        <div style={css("display:flex;align-items:baseline;gap:9px")}>
          <span style={css("font-size:19px;font-weight:600;color:#16262c;letter-spacing:-.01em")}>
            Full Shelf
          </span>
          <span
            className="mono"
            style={css("font-size:9.5px;letter-spacing:.14em;color:#74848a")}
          >
            FULFILLMENT CONTROL PLANE
          </span>
        </div>

        <p style={css("font-size:13px;line-height:1.55;color:#4d5f66;margin:0")}>
          This demonstration is private. Sign in with the credentials supplied
          in the submission.
        </p>

        <label style={css("display:flex;flex-direction:column;gap:5px")}>
          <span
            className="mono"
            style={css("font-size:9.5px;letter-spacing:.1em;color:#74848a;font-weight:700")}
          >
            USERNAME
          </span>
          <input
            data-testid="judge-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
            style={css(
              "border:1px solid #cdd4d0;border-radius:8px;padding:10px 12px;" +
                "font-size:14px;background:#fff;color:#16262c",
            )}
          />
        </label>

        <label style={css("display:flex;flex-direction:column;gap:5px")}>
          <span
            className="mono"
            style={css("font-size:9.5px;letter-spacing:.1em;color:#74848a;font-weight:700")}
          >
            PASSWORD
          </span>
          <input
            data-testid="judge-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            style={css(
              "border:1px solid #cdd4d0;border-radius:8px;padding:10px 12px;" +
                "font-size:14px;background:#fff;color:#16262c",
            )}
          />
        </label>

        {error ? (
          <div
            data-testid="judge-login-error"
            role="alert"
            style={css(
              "background:#f3e5e1;border:1px solid #e3c3ba;border-left:4px solid #a23b2b;" +
                "border-radius:8px;padding:9px 12px;font-size:12.5px;color:#8a2f22",
            )}
          >
            {error}
          </div>
        ) : null}

        <button
          type="submit"
          data-testid="judge-signin"
          disabled={busy}
          style={css(
            `background:${busy ? "#4a6a74" : "#16323b"};color:#eef4f4;border:none;` +
              "border-radius:8px;padding:11px 16px;font-size:13.5px;font-weight:600;" +
              `cursor:${busy ? "wait" : "pointer"}`,
          )}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p
          className="mono"
          style={css("font-size:9.5px;line-height:1.6;color:#8a969a;margin:0")}
        >
          Authentication by Google Cloud Identity Platform. Full Shelf never
          sees or stores your password.
        </p>
      </form>
    </div>
  );
}
