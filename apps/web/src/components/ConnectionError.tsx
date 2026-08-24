// =====================================================================
// Full Shelf — connection-error surface (v6.1)
// ---------------------------------------------------------------------
// Shown whenever the datasource fails. The control plane shows NOTHING
// rather than stale or unverified data: no cached projection, no last
// known values, no partial workspace.
//
// Reconnect performs a real retry against the same boundary. It is not a
// cosmetic reset, and it does not fabricate a recovered state.
// =====================================================================

import { css } from "../styles/css";

export function ConnectionError({
  detail,
  onReconnect,
}: {
  detail: string;
  onReconnect: () => void;
}) {
  return (
    <div
      role="alert"
      data-testid="connection-error"
      style={css(
        "flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;" +
          "gap:13px;background:#eef0ea;padding:24px",
      )}
    >
      <div
        style={css(
          "width:46px;height:46px;border-radius:50%;background:#f5e1dc;border:1px solid #e6bcb0;" +
            "display:flex;align-items:center;justify-content:center;font-size:22px;color:#9a3322",
        )}
      >
        ⚠
      </div>
      <div style={css("font-size:16px;font-weight:600;color:#16262c")}>
        Connection to the control plane lost
      </div>
      <div
        className="mono"
        style={css("font-size:11.5px;color:#74848a;max-width:420px;text-align:center;line-height:1.6")}
      >
        Authoritative state is unavailable. The control plane shows nothing rather than stale or
        unverified data.
      </div>
      {detail ? (
        <div
          className="mono"
          data-testid="connection-error-detail"
          style={css("font-size:10px;color:#9aa6ab;max-width:520px;text-align:center;line-height:1.5")}
        >
          {detail}
        </div>
      ) : null}
      <button
        type="button"
        onClick={onReconnect}
        data-testid="reconnect"
        style={css(
          "margin-top:4px;background:#16323b;color:#eef4f4;border:none;border-radius:7px;" +
            "padding:9px 18px;font-size:12.5px;font-weight:600;cursor:pointer",
        )}
      >
        Reconnect
      </button>
    </div>
  );
}
