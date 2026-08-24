import { css } from "../styles/css";
import { TONE, toneGlyph } from "../styles/tokens";
import type { BeatId, TomorrowView } from "../types/fullShelf";

export function TomorrowsDraft({ tomorrow, onGo }: { tomorrow: TomorrowView; onGo: (b: BeatId) => void }) {
  return (
    <>
      <div style={css("display:flex;align-items:center;gap:10px;margin-bottom:12px")}>
        <span role="button" tabIndex={0} onClick={() => onGo("todaysOutcome")} onKeyDown={(e) => e.key === "Enter" && onGo("todaysOutcome")} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>← Today's outcome</span>
        <span className="mono" style={css("font-size:11px;color:#93a1a6")}>/</span>
        <span className="mono" style={css("font-size:12px;color:#74848a;letter-spacing:.02em")}>Next operating day · draft</span>
      </div>
      <div style={css("display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:18px")}>
        <div>
          <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#74848a;font-weight:600")}>{tomorrow.preparedNote}</div>
          <div style={css("display:flex;align-items:center;gap:14px;margin-top:5px")}>
            <h1 style={css("font-size:27px;font-weight:600;letter-spacing:-.01em")}>{tomorrow.dayLabel}</h1>
            <span className="mono" style={css("font-size:12px;font-weight:600;padding:4px 9px;border-radius:5px;background:#f6ebd9;color:#a85f12;border:1px solid #e6cfa4")}>▲ {tomorrow.status}</span>
          </div>
        </div>
        <div style={css("background:#16323b;color:#f4f6f5;border-radius:8px;padding:10px 16px")}>
          <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#f0c987;font-weight:600")}>▲ HUMAN APPROVAL REQUIRED</div>
          <div style={css("font-size:12px;color:#c8d5d8;margin-top:2px")}>{tomorrow.approvalNote}</div>
        </div>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 360px;gap:18px;align-items:start")}>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;overflow:hidden")}>
          <div style={css("padding:13px 16px;border-bottom:1px solid #eceee9;display:flex;align-items:center;justify-content:space-between")}>
            <span style={css("font-size:14px;font-weight:600")}>Tomorrow · Plan rev01 (draft)</span>
            <span className="mono" style={css("font-size:12px;color:#74848a")}>proposed · advisory until approved</span>
          </div>
          <div style={css("padding:16px 18px")}>
            <div style={css("display:flex;flex-direction:column;gap:10px")}>
              {tomorrow.draftRows.map((d, i) => {
                const t = TONE[d.tone];
                return (
                  <div key={i} style={css(`display:flex;gap:10px;align-items:flex-start;padding:11px 13px;background:${t.bg};border:1px solid ${t.border};border-radius:8px`)}>
                    <span className="mono" style={css(`font-size:12px;color:${t.accent};margin-top:1px`)}>{toneGlyph(d.tone)}</span>
                    <div>
                      <div style={css(`font-size:13px;font-weight:600;color:${t.fg}`)}>{d.title}</div>
                      <div style={css(`font-size:12px;color:${t.fg};margin-top:1px`)}>{d.body}</div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={css("margin-top:14px;padding:11px 13px;background:#faf9f5;border:1px dashed #d5d8d2;border-radius:7px;font-size:12px;color:#74848a;line-height:1.5")}>{tomorrow.planNote}</div>
          </div>
        </div>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:16px")}>
          <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:12px")}>INHERITED OPEN OBLIGATIONS</div>
          <div style={css("font-size:12px;color:#74848a;margin-bottom:12px;line-height:1.4")}>Durable objects carried from Fri Aug 14. Traceable to their origin.</div>
          <div style={css("display:flex;flex-direction:column;gap:11px")}>
            {tomorrow.inheritedObligations.map((o) => (
              <div key={o.id} style={css("border:1px solid #e6cfa4;border-radius:8px;padding:12px")}>
                <div style={css("display:flex;justify-content:space-between;align-items:center")}>
                  <span className="mono" style={css("font-size:12px;font-weight:600")}>{o.id}</span>
                  <span className="mono" style={css("font-size:11px;font-weight:600;padding:2px 7px;border-radius:4px;background:#f6ebd9;color:#a85f12")}>▲ {o.badge}</span>
                </div>
                <div style={css("font-size:12px;margin-top:6px")}>{o.title}</div>
                <div className="mono" style={css("font-size:11px;color:#74848a;margin-top:4px")}>{o.origin}</div>
              </div>
            ))}
          </div>
          <div style={css("margin-top:13px;font-size:12px;color:#74848a;line-height:1.5")}>{tomorrow.carryNote}</div>
        </div>
      </div>
    </>
  );
}
