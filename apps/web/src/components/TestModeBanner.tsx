import { css } from "../styles/css";

interface TestControl {
  id: string;
  label: string;
  active: boolean;
  onClick: () => void;
}

export function TestModeBanner({ dataMode, controls = [] }: { dataMode: string; controls?: TestControl[] }) {
  if (dataMode !== "SYNTHETIC_TEST") return null;
  return (
    <div style={css("display:flex;align-items:center;gap:12px;background:#3a2f12;color:#f5ecd4;border-radius:9px;padding:9px 15px;margin-bottom:12px")}>
      <span className="mono" style={css("font-size:10px;font-weight:700;letter-spacing:.16em;background:#c79a2e;color:#241c07;padding:3px 9px;border-radius:4px")}>
        DETERMINISTIC TEST MODE
      </span>
      <span className="mono" style={css("font-size:11px;color:#e6d6a8;letter-spacing:.02em")}>{dataMode}</span>
      {controls.length ? (
        <div aria-label="Deterministic replay moments" style={css("margin-left:auto;display:flex;align-items:center;gap:5px")}>
          <span className="mono" style={css("font-size:8px;color:#cbb87e;letter-spacing:.08em;margin-right:3px")}>REPLAY</span>
          {controls.map((control) => (
            <button
              key={control.id}
              type="button"
              data-testid={control.id}
              aria-pressed={control.active}
              onClick={control.onClick}
              style={css(`border:1px solid ${control.active ? "#e2b84d" : "#76632f"};background:${control.active ? "#d3a83b" : "transparent"};color:${control.active ? "#241c07" : "#dbc98f"};border-radius:4px;padding:3px 7px;font-size:8.5px;font-weight:700;cursor:pointer`)}
            >
              {control.label}
            </button>
          ))}
        </div>
      ) : (
        <span style={css("margin-left:auto;font-size:11px;color:#cbb87e")}>
          All values are deterministic synthetic fixtures — no live backend, receipts, or signatures.
        </span>
      )}
    </div>
  );
}
