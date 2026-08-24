import { css } from "../styles/css";
import { CONN } from "../styles/tokens";
import type { Connection } from "../types/fullShelf";

interface Props {
  clock: string;
  operatingDate: string;
  connection: Connection;
  isHistory: boolean;
  onToday: () => void;
  onHistory: () => void;
  onOpenEvidence: () => void;
  onToggleConnection: () => void;
}

export function TopBar({ clock, operatingDate, connection, isHistory, onToday, onHistory, onOpenEvidence, onToggleConnection }: Props) {
  const conn = CONN[connection];
  const navToday = isHistory ? { bg: "transparent", fg: "#cfe0e4" } : { bg: "#1f6f8b", fg: "#ffffff" };
  const navHistory = isHistory ? { bg: "#1f6f8b", fg: "#ffffff" } : { bg: "transparent", fg: "#cfe0e4" };
  return (
    <div style={css("background:#16323b;color:#f4f6f5;display:flex;align-items:center;justify-content:space-between;padding:0 24px;height:56px;flex:none")}>
      <div style={css("display:flex;align-items:center;gap:28px")}>
        <div style={css("display:flex;align-items:baseline;gap:9px")}>
          <span style={css("font-size:17px;font-weight:600;letter-spacing:-.01em")}>Full Shelf</span>
          <span className="mono" style={css("font-size:11px;letter-spacing:.14em;color:#8296a0")}>FULFILLMENT CONTROL PLANE</span>
        </div>
        <div style={css("display:flex;gap:4px")}>
          <div role="button" tabIndex={0} onClick={onToday} onKeyDown={(e) => e.key === "Enter" && onToday()} style={css(`font-size:13px;font-weight:600;padding:7px 14px;border-radius:6px;cursor:pointer;background:${navToday.bg};color:${navToday.fg}`)}>Today</div>
          <div role="button" tabIndex={0} onClick={onHistory} onKeyDown={(e) => e.key === "Enter" && onHistory()} style={css(`font-size:13px;font-weight:500;padding:7px 14px;border-radius:6px;cursor:pointer;background:${navHistory.bg};color:${navHistory.fg}`)}>History</div>
        </div>
      </div>
      <div style={css("display:flex;align-items:center;gap:16px")}>
        <div className="fs-topchip" role="button" tabIndex={0} onClick={onOpenEvidence} onKeyDown={(e) => e.key === "Enter" && onOpenEvidence()} style={css("display:flex;align-items:center;gap:7px;background:#1e3d47;border:1px solid #2c545f;border-radius:6px;padding:6px 11px;cursor:pointer")}>
          <span className="mono" style={css("font-size:12px;color:#cfe0e4;font-weight:600")}>Execution record</span>
        </div>
        <div style={css("text-align:right;line-height:1.25")}>
          <div className="mono" style={css("font-size:12px;font-weight:600;color:#f4f6f5")}>{clock}</div>
          <div className="mono" style={css("font-size:11px;color:#a4b4ba;letter-spacing:.04em")}>{operatingDate}</div>
        </div>
        <div role="button" tabIndex={0} title="Toggle connection (test)" onClick={onToggleConnection} onKeyDown={(e) => e.key === "Enter" && onToggleConnection()} style={css("display:flex;align-items:center;gap:7px;background:#1e3d47;border:1px solid #2c545f;border-radius:20px;padding:5px 12px 5px 10px;cursor:pointer")}>
          <span className="fs-pulse" style={css(`width:8px;height:8px;border-radius:50%;background:${conn.dot};box-shadow:0 0 0 3px ${conn.glow}`)} />
          <span style={css("font-size:12px;font-weight:600;color:#cfe0e4")}>{conn.label}</span>
        </div>
      </div>
    </div>
  );
}
