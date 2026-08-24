import { css } from "../styles/css";
import type { BeatId } from "../types/fullShelf";

interface Props {
  ref_: string;
  postureLabel: string;
  activeBeat: BeatId;
  onToday: () => void;
  onGo: (b: BeatId) => void;
}

const SECTIONS: [string, string, BeatId][] = [
  ["E1", "Custody impact", "custodyEstablished"],
  ["E2", "Governed recovery", "governedRecovery"],
  ["E3", "Governance & refusal", "governanceRefusal"],
];

export function IncidentRail({ ref_, postureLabel, activeBeat, onToday, onGo }: Props) {
  return (
    <>
      <div style={css("display:flex;align-items:center;gap:10px;margin-bottom:12px")}>
        <span role="button" tabIndex={0} onClick={onToday} onKeyDown={(e) => e.key === "Enter" && onToday()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>← Today</span>
        <span className="mono" style={css("font-size:11px;color:#93a1a6")}>/</span>
        <span className="mono" style={css("font-size:12px;color:#74848a;letter-spacing:.02em")}>Recall {ref_} · lot LTC-4471</span>
        <span className="mono" style={css("margin-left:auto;font-size:11px;font-weight:600;padding:4px 9px;border-radius:5px;background:#f6ebd9;color:#a85f12;border:1px solid #e6cfa4")}>▲ {postureLabel}</span>
      </div>
      <div style={css("display:flex;gap:6px;background:#e6e8e4;border:1px solid #d5d8d2;border-radius:10px;padding:5px;margin-bottom:18px")}>
        {SECTIONS.map(([num, label, target]) => {
          const active = activeBeat === target;
          return (
            <button key={num} type="button" onClick={() => onGo(target)} style={css(`flex:1;border:none;border-radius:7px;padding:9px 12px;text-align:left;cursor:pointer;background:${active ? "#fff" : "transparent"};font-family:'IBM Plex Sans',sans-serif`)}>
              <div style={css("display:flex;align-items:center;gap:7px")}>
                <span className="mono" style={css(`font-size:11px;font-weight:600;color:${active ? "#1f6f8b" : "#74848a"}`)}>{num}</span>
                <span style={css(`font-size:13px;font-weight:600;color:${active ? "#16323b" : "#43555c"}`)}>{label}</span>
                <span className="mono" style={css(`margin-left:auto;font-size:10px;font-weight:600;color:${active ? "#1f6f8b" : "#74848a"}`)}>{active ? "VIEWING" : "OPEN"}</span>
              </div>
            </button>
          );
        })}
      </div>
    </>
  );
}
