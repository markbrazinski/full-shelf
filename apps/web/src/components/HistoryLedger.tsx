import { css } from "../styles/css";
import { TONE } from "../styles/tokens";
import type { HistoryView } from "../types/fullShelf";

export function HistoryLedger({ history, onToday }: { history: HistoryView; onToday: () => void }) {
  return (
    <>
      <div style={css("display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:18px")}>
        <div>
          <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#74848a;font-weight:600")}>HISTORY · READ-ONLY</div>
          <h1 style={css("font-size:27px;font-weight:600;letter-spacing:-.01em;margin-top:5px")}>Authority &amp; activity ledger</h1>
          <div style={css("font-size:12px;color:#43555c;margin-top:3px")}>Events committed as of {history.asOf}. Provenance only — the current authoritative state is unchanged.</div>
        </div>
        <span role="button" tabIndex={0} onClick={onToday} onKeyDown={(e) => e.key === "Enter" && onToday()} style={css("font-size:12px;font-weight:600;background:#16323b;color:#f4f6f5;padding:9px 15px;border-radius:6px;cursor:pointer")}>Return to current Today →</span>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 340px;gap:18px;align-items:start")}>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;overflow:hidden")}>
          <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;padding:13px 16px;border-bottom:1px solid #eceee9")}>OPERATING DAY · FRI AUG 14</div>
          {history.ledger.map((l, i) => {
            const t = TONE[l.tone];
            const tg = TONE[l.tag.tone];
            const titleFg = t.fg === "#5c6b71" ? "#16323b" : t.fg;
            return (
              <div key={i} style={css("display:grid;grid-template-columns:70px 1fr auto;column-gap:14px;padding:11px 16px;border-bottom:1px solid #f2f1ec;align-items:center")}>
                <span className="mono" style={css(`font-size:12px;font-weight:600;color:${t.accent}`)}>{l.time}</span>
                <div>
                  <div style={css(`font-size:13px;font-weight:600;color:${titleFg}`)}>{l.title}</div>
                  <div className="mono" style={css("font-size:11px;color:#74848a;margin-top:1px")}>{l.meta}</div>
                </div>
                <span className="mono" style={css(`font-size:11px;font-weight:600;padding:3px 8px;border-radius:5px;background:${tg.bg};color:${tg.accent};border:1px solid ${tg.border}`)}>{l.tag.label}</span>
              </div>
            );
          })}
        </div>
        <div style={css("display:flex;flex-direction:column;gap:14px")}>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:11px")}>PLAN REVISION LINEAGE</div>
            <div style={css("display:flex;flex-direction:column;gap:9px")}>
              {history.lineage.map((v, i) => (
                <div key={i} style={css("display:flex;align-items:center;gap:9px")}>
                  <span className="mono" style={css(`font-size:12px;color:${TONE[v.tone].accent}`)}>{v.glyph}</span>
                  <span style={css("font-size:12px")}>{v.text}</span>
                </div>
              ))}
            </div>
          </div>
          <div style={css("background:#f0f4f5;border:1px solid #dfe4e0;border-radius:10px;padding:14px 16px")}>
            <div style={css("font-size:12px;color:#43555c;line-height:1.5")}>{history.note}</div>
          </div>
        </div>
      </div>
    </>
  );
}
