import { css } from "../styles/css";
import { CUS_POS, CUS_ST } from "../styles/tokens";
import type { CustodyView } from "../types/fullShelf";

export function CustodyGraph({ custody, onOpenEvidence }: { custody: CustodyView; onOpenEvidence: () => void }) {
  return (
    <>
      <div style={css("display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:14px")}>
        <div>
          <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#74848a;font-weight:600")}>CUSTODY IMPACT · NON-GEOGRAPHIC GRAPH</div>
          {/* The benefit leads. The question it answers is the subhead. */}
          <h1
            style={css("font-size:24px;font-weight:600;letter-spacing:-.01em;margin-top:5px")}
            data-testid="custody-headline"
          >
            {custody.headline}
          </h1>
          <div style={css("font-size:13px;color:#5c6b71;margin-top:5px;line-height:1.5;max-width:640px")}>
            {custody.headlineDetail}
          </div>
        </div>
        <div style={css("text-align:right")}>
          <div className="mono" style={css("font-size:12px;color:#74848a")}>CURRENT-POSITION UNIQUE</div>
          <div className="mono" style={css("font-size:30px;font-weight:600;color:#16323b")}>{custody.totalUnique}</div>
        </div>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 360px;gap:18px;align-items:start")}>
        <div style={css("background:#eef1ee;border:1px solid #d5d8d2;border-radius:12px;padding:18px;overflow:hidden")}>
          <div style={css("position:relative;width:100%;height:470px")}>
            <svg viewBox="0 0 720 470" preserveAspectRatio="xMidYMid meet" style={css("position:absolute;inset:0;width:100%;height:100%")} fill="none" strokeLinecap="round">
              <defs>
                <marker id="cg-grey2" markerWidth="7" markerHeight="7" refX="5.2" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#8a938f" /></marker>
                <marker id="cg-amber3" markerWidth="7" markerHeight="7" refX="5.2" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#a85f12" /></marker>
              </defs>
              <g stroke="#aeb8ba" strokeWidth="2">
                <path d="M150,232 L214,41" markerEnd="url(#cg-grey2)" />
                <path d="M150,232 L214,109" markerEnd="url(#cg-grey2)" />
                <path d="M150,232 L214,177" markerEnd="url(#cg-grey2)" />
                <path d="M150,232 L214,245" markerEnd="url(#cg-grey2)" />
                <path d="M388,332 L494,308" markerEnd="url(#cg-grey2)" />
              </g>
              <path d="M388,338 L494,398" stroke="#a85f12" strokeWidth="3" strokeDasharray="6 5" markerEnd="url(#cg-amber3)" />
              <text x="430" y="304" fontFamily="'IBM Plex Mono',monospace" fontSize="11" fontWeight="600" fill="#74848a">retains 10</text>
              <text x="420" y="392" fontFamily="'IBM Plex Mono',monospace" fontSize="11" fontWeight="700" fill="#a85f12">8 forwarded →</text>
            </svg>
            <div style={css("position:absolute;left:0px;top:180px;width:146px;background:#16323b;color:#f4f6f5;border-radius:11px;padding:12px 13px")}>
              <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#8fa6ac")}>LOT · SOURCE</div>
              <div className="mono" style={css("font-size:15px;font-weight:600;margin-top:3px")}>LTC-4471</div>
              <div className="mono" style={css("font-size:12px;color:#cfe0e4;margin-top:7px")}>{custody.totalUnique} unique cases</div>
            </div>
            {custody.nodes.map((n) => {
              const st = CUS_ST[n.status];
              const pos = CUS_POS[n.key] ?? { left: 212, top: 14 };
              const width = pos.width ?? 172;
              return (
                <div key={n.key} style={css(`position:absolute;left:${pos.left}px;top:${pos.top}px;width:${width}px;background:#fff;border:1px solid ${st.border};border-left:4px solid ${st.accent};border-radius:9px;padding:9px 12px`)}>
                  <div style={css("display:flex;justify-content:space-between;align-items:center")}>
                    <span style={css("font-size:12px;font-weight:600")}>
                      {n.label}
                      {/* Role is presentation metadata; the name, quantity
                          and custody state all come from the projection. */}
                      {n.roleLabel ? (
                        <span style={css("font-weight:400;color:#74848a")}> · {n.roleLabel}</span>
                      ) : null}
                    </span>
                    <span className="mono" style={css("font-size:17px;font-weight:600")}>{n.value}</span>
                  </div>
                  {n.note && <div className="mono" style={css("font-size:11px;color:#a85f12;margin-top:3px")}>{n.note}</div>}
                  <div style={css("margin-top:5px")}>
                    <span className="mono" style={css(`font-size:10px;font-weight:600;padding:2px 6px;border-radius:4px;background:${st.bg};color:${st.fg};border:1px solid ${st.border}`)}>{st.glyph} {st.label}</span>
                  </div>
                </div>
              );
            })}
          </div>
          <div style={css("margin-top:14px;padding-top:12px;border-top:1px solid #d5d8d2;display:flex;flex-wrap:wrap;gap:14px;align-items:center")}>
            <LegendItem color="#6b7b81" glyph="●" text="Confirmed custody / disposition" />
            <LegendItem color="#a23b2b" glyph="■" text="Blocked movement" />
            <LegendItem color="#a85f12" glyph="▲" text="Unconfirmed" />
            <span style={css("font-size:12px;color:#8a2f22;font-weight:600")}>{custody.caveat}</span>
          </div>
        </div>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;overflow:hidden")}>
          <div style={css("display:flex;align-items:center;justify-content:space-between;padding:12px 15px;border-bottom:1px solid #eceee9")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600")}>RECONCILIATION · CURRENT POSITIONS</div>
            <span role="button" tabIndex={0} onClick={onOpenEvidence} onKeyDown={(e) => e.key === "Enter" && onOpenEvidence()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>Record →</span>
          </div>
          {custody.reconciliation.map((r, i) => {
            const fg = r.muted ? "#8a8f88" : r.tone === "warn" ? "#a85f12" : "#1a2a30";
            const valFg = r.muted ? "#8a8f88" : r.tone === "warn" ? "#a85f12" : "#16323b";
            return (
              <div key={i} style={css(`display:flex;justify-content:space-between;padding:9px 15px;border-bottom:1px solid #f2f1ec;background:${r.muted ? "#f7f6f1" : "#fff"}`)}>
                <span style={css(`font-size:12px;color:${fg}`)}>{r.label}</span>
                <span className="mono" style={css(`font-size:12px;font-weight:600;color:${valFg}`)}>{r.value}</span>
              </div>
            );
          })}
          <div style={css("display:flex;justify-content:space-between;padding:11px 15px;background:#f0f4f5")}>
            <span style={css("font-size:12px;font-weight:600")}>Total unique</span>
            <span className="mono" style={css("font-size:14px;font-weight:600;color:#16323b")}>{custody.totalUnique}</span>
          </div>
          <div className="mono" style={css("font-size:11px;color:#74848a;padding:8px 15px;text-align:center;border-top:1px solid #eceee9")}>{custody.sumExpression}</div>
        </div>
      </div>
    </>
  );
}

function LegendItem({ color, glyph, text }: { color: string; glyph: string; text: string }) {
  return (
    <span style={css("display:flex;align-items:center;gap:6px;font-size:12px;color:#43555c")}>
      <span className="mono" style={css(`color:${color}`)}>{glyph}</span> {text}
    </span>
  );
}
