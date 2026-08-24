import { css } from "../styles/css";
import type { BeatId, BeatMeta } from "../types/fullShelf";

interface Props {
  beats: BeatMeta[];
  activeBeat: BeatId;
  onGo: (b: BeatId) => void;
}

export function StateNavigator({ beats, activeBeat, onGo }: Props) {
  return (
    <div style={css("border:1px dashed #b9a97e;background:#efe7d5;border-radius:10px;padding:10px 13px 11px;margin-bottom:14px")}>
      <div className="mono" style={css("font-size:10px;letter-spacing:.12em;color:#9a8552;font-weight:600;margin-bottom:7px")}>
        STATE NAVIGATOR · 12 PRODUCT VIEWS + HISTORY · SYNTHETIC_TEST
      </div>
      <div style={css("display:flex;gap:5px;flex-wrap:wrap")}>
        {beats.map((b) => {
          const active = b.id === activeBeat;
          return (
            <button
              key={b.id}
              type="button"
              data-beat={b.id}
              onClick={() => onGo(b.id)}
              style={css(
                `flex:1;min-width:86px;background:${active ? "#16323b" : "#fff"};color:${active ? "#fff" : "#43555c"};border:1px solid ${active ? "#16323b" : "#d5d8d2"};border-radius:6px;padding:6px 8px;cursor:pointer;text-align:left;line-height:1.15;font-family:'IBM Plex Sans',sans-serif`,
              )}
            >
              <div className="mono" style={css(`font-size:10px;font-weight:600;color:${active ? "#cfe0e4" : "#93a1a6"}`)}>{b.time}</div>
              <div style={css("font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis")}>{b.label}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
