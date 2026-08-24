import { css } from "../styles/css";

export function TestModeBanner({ dataMode }: { dataMode: string }) {
  if (dataMode !== "SYNTHETIC_TEST") return null;
  return (
    <div style={css("display:flex;align-items:center;gap:12px;background:#3a2f12;color:#f5ecd4;border-radius:9px;padding:9px 15px;margin-bottom:12px")}>
      <span className="mono" style={css("font-size:10px;font-weight:700;letter-spacing:.16em;background:#c79a2e;color:#241c07;padding:3px 9px;border-radius:4px")}>
        DETERMINISTIC TEST MODE
      </span>
      <span className="mono" style={css("font-size:11px;color:#e6d6a8;letter-spacing:.02em")}>{dataMode}</span>
      <span style={css("margin-left:auto;font-size:11px;color:#cbb87e")}>
        All values are deterministic synthetic fixtures — no live backend, receipts, or signatures.
      </span>
    </div>
  );
}
