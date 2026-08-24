import { css } from "../styles/css";
import { TONE } from "../styles/tokens";
import type { BeatId, OutcomeView } from "../types/fullShelf";

export function TodaysOutcome({ outcome, onGo }: { outcome: OutcomeView; onGo: (b: BeatId) => void }) {
  return (
    <>
      <div style={css("display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:18px")}>
        <div>
          <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#74848a;font-weight:600")}>OPERATING DAY · TODAY'S OUTCOME</div>
          <h1 style={css("font-size:27px;font-weight:600;letter-spacing:-.01em;margin-top:5px")}>{outcome.dayLabel}</h1>
        </div>
        <span className="mono" style={css("font-size:12px;font-weight:600;padding:6px 12px;border-radius:6px;background:#f6ebd9;color:#a85f12;border:1px solid #e6cfa4")}>▲ INCIDENT {outcome.posture}</span>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start")}>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:12px;overflow:hidden")}>
          <div style={css("padding:14px 18px;border-bottom:1px solid #eceee9;background:#f0f4f5")}>
            <div style={css("font-size:15px;font-weight:600")}>Service outcome</div>
            <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#74848a;margin-top:2px")}>DID SITES RECEIVE FOOD?</div>
          </div>
          <div style={css("padding:18px")}>
            <div style={css("display:flex;align-items:baseline;gap:10px;margin-bottom:16px")}>
              <span className="mono" style={css("font-size:34px;font-weight:600;color:#3f7d5a")}>{outcome.service.fulfilledCount}</span>
              <span style={css("font-size:14px;color:#43555c")}>{outcome.service.fulfilledLabel}</span>
            </div>
            <div style={css("display:flex;flex-direction:column;gap:8px")}>
              <div style={css("display:flex;justify-content:space-between;padding:9px 12px;background:#e5efe9;border:1px solid #c4ddce;border-radius:7px")}>
                <span style={css("font-size:12px;color:#2f5f45")}>{outcome.service.fulfilledList}</span>
                <span className="mono" style={css("font-size:11px;font-weight:600;color:#3f7d5a")}>● FULFILLED</span>
              </div>
              <div style={css("display:flex;justify-content:space-between;padding:9px 12px;background:#f6ebd9;border:1px solid #e6cfa4;border-radius:7px")}>
                <span style={css("font-size:12px;color:#8a6a1f;font-weight:600")}>{outcome.service.unfulfilled.label}</span>
                <span className="mono" style={css("font-size:11px;font-weight:600;color:#a85f12")}>▲ {outcome.service.unfulfilled.badge}</span>
              </div>
            </div>
            <div style={css("margin-top:13px;font-size:12px;color:#74848a;line-height:1.5")}>{outcome.service.note}</div>
          </div>
        </div>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:12px;overflow:hidden")}>
          <div style={css("padding:14px 18px;border-bottom:1px solid #eceee9;background:#f0f4f5")}>
            <div style={css("font-size:15px;font-weight:600")}>Safety outcome</div>
            <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#74848a;margin-top:2px")}>IS THE RECALLED LOT ACCOUNTED FOR?</div>
          </div>
          <div style={css("padding:18px")}>
            <div style={css("display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px")}>
              <div style={css("background:#f0f4f5;border:1px solid #dfe4e0;border-radius:8px;padding:11px 13px")}>
                <div className="mono" style={css("font-size:24px;font-weight:600;color:#16323b")}>{outcome.safety.traced}</div>
                <div style={css("font-size:12px;color:#43555c")}>unique cases traced</div>
              </div>
              <div style={css("background:#e5efe9;border:1px solid #c4ddce;border-radius:8px;padding:11px 13px")}>
                <div className="mono" style={css("font-size:24px;font-weight:600;color:#3f7d5a")}>{outcome.safety.confirmed}</div>
                <div style={css("font-size:12px;color:#2f5f45")}>confirmed custody / disposition</div>
              </div>
            </div>
            <div style={css("background:#f3e5e1;border:1px solid #e3c3ba;border-radius:8px;padding:11px 13px;margin-bottom:12px")}>
              <div style={css("font-size:12px;font-weight:600;color:#8a2f22")}>{outcome.safety.caveatTitle}</div>
              <div style={css("font-size:12px;color:#8a2f22;margin-top:3px;line-height:1.45")}>{outcome.safety.caveatBody}</div>
            </div>
            <div style={css("display:flex;flex-direction:column;gap:8px")}>
              {outcome.safety.rows.map((s, i) => {
                const t = TONE[s.tone];
                return (
                  <div key={i} style={css(`display:flex;justify-content:space-between;padding:9px 12px;background:${t.bg};border:1px solid ${t.border};border-radius:7px`)}>
                    <span style={css(`font-size:12px;color:${t.fg}`)}>{s.label}</span>
                    <span className="mono" style={css(`font-size:11px;font-weight:600;color:${t.accent}`)}>{s.tone === "crit" ? "■" : "▲"} {s.badge}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
      <div style={css("margin-top:18px;background:#fff;border:1px solid #d5d8d2;border-radius:12px;padding:16px 18px")}>
        <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:12px")}>NEXT UNRESOLVED REQUIREMENTS</div>
        <div style={css("display:grid;grid-template-columns:1fr 1fr;gap:14px")}>
          {outcome.nextRequirements.map((n, i) => {
            const isWarn = n.tone === "warn";
            return (
              <div key={i} style={css(`display:flex;align-items:center;gap:12px;border:1px solid ${isWarn ? "#e6cfa4" : "#d5d8d2"};border-radius:9px;padding:13px 14px;background:${isWarn ? "#fdf9f0" : "#fff"}`)}>
                <div style={css("flex:1")}>
                  <div style={css("display:flex;align-items:center;gap:8px")}>
                    {n.id && <span className="mono" style={css("font-size:12px;font-weight:600")}>{n.id}</span>}
                    {n.badge && <span className="mono" style={css("font-size:10px;font-weight:600;padding:2px 7px;border-radius:4px;background:#f6ebd9;color:#a85f12")}>▲ {n.badge}</span>}
                  </div>
                  <div style={css(`font-size:${n.id ? "12px" : "13px"};font-weight:600;color:${n.id ? "#8a6a1f" : "#16323b"};margin-top:4px`)}>{n.title}</div>
                  {n.body && <div style={css("font-size:12px;color:#74848a;margin-top:4px")}>{n.body}</div>}
                </div>
                <button type="button" className="fs-brighten" onClick={() => onGo(n.action.target)} style={css(`flex:none;background:${isWarn ? "#a85f12" : "#16323b"};color:#fff;border:none;border-radius:7px;padding:10px 14px;font-size:12px;font-weight:600;cursor:pointer;font-family:'IBM Plex Sans',sans-serif`)}>{n.action.label}</button>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
