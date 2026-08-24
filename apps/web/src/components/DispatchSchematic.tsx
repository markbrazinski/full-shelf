import { css } from "../styles/css";
import type { BeatId, DispatchView } from "../types/fullShelf";

interface Props {
  dispatch: DispatchView;
  onToday: () => void;
  onGo: (b: BeatId) => void;
}

export function DispatchSchematic({ dispatch, onToday, onGo }: Props) {
  const s = dispatch.stops;
  const v = dispatch.vehicles;
  const cap = dispatch.capacityDecision;
  return (
    <>
      <div style={css("display:flex;align-items:center;gap:10px;margin-bottom:14px")}>
        <span role="button" tabIndex={0} onClick={onToday} onKeyDown={(e) => e.key === "Enter" && onToday()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>← Today</span>
        <span className="mono" style={css("font-size:11px;color:#93a1a6")}>/</span>
        <span role="button" tabIndex={0} onClick={() => onGo("revisionReview")} onKeyDown={(e) => e.key === "Enter" && onGo("revisionReview")} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>Proposed rev08</span>
        <span className="mono" style={css("font-size:11px;color:#93a1a6")}>/</span>
        <span className="mono" style={css("font-size:12px;color:#74848a;letter-spacing:.02em")}>Dispatch schematic · 08:20</span>
      </div>
      <div style={css("display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:14px")}>
        <div>
          <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#74848a;font-weight:600")}>CONTEXTUAL DISPATCH VIEW</div>
          <h1 style={css("font-size:25px;font-weight:600;letter-spacing:-.01em;margin-top:5px")}>{dispatch.title}</h1>
          <div style={css("font-size:12px;color:#43555c;margin-top:3px")}>{dispatch.note}</div>
        </div>
        <div style={css("text-align:right")}>
          <span className="mono" style={css("font-size:11px;font-weight:600;padding:5px 10px;border-radius:5px;background:#f6ebd9;color:#a85f12;border:1px solid #e6cfa4")}>{dispatch.schematicLabel}</span>
          <div className="mono" style={css("font-size:11px;letter-spacing:.04em;color:#93a1a6;margin-top:5px")}>Committed assignments · no positions or bearings</div>
        </div>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 380px;gap:18px;align-items:start")}>
        <div style={css("background:#eef1ee;border:1px solid #ccd5d7;border-radius:12px;padding:14px")}>
          <div style={css("position:relative;width:100%;height:460px;background:#e7ebe7;border-radius:9px;overflow:hidden;border:1px solid #dbe1dc")}>
            <svg viewBox="0 0 820 460" preserveAspectRatio="xMidYMid meet" style={css("position:absolute;inset:0;width:100%;height:100%")} fill="none" strokeLinecap="round" strokeLinejoin="round">
              <defs>
                <marker id="mk-blue2" markerWidth="8" markerHeight="8" refX="5.6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#1f6f8b" /></marker>
                <marker id="mk-amber2" markerWidth="8" markerHeight="8" refX="5.6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#a85f12" /></marker>
                <marker id="mk-green2" markerWidth="8" markerHeight="8" refX="5.6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#3f7d5a" /></marker>
              </defs>
              <rect x="452" y="112" width="150" height="92" rx="12" fill="#e0e8df" />
              <rect x="70" y="286" width="120" height="120" rx="12" fill="#dde8ec" />
              <g stroke="#dbe2dd" strokeWidth="12">
                <line x1="0" y1="90" x2="820" y2="90" /><line x1="0" y1="232" x2="820" y2="232" /><line x1="0" y1="368" x2="820" y2="368" />
                <line x1="210" y1="0" x2="210" y2="460" /><line x1="430" y1="0" x2="430" y2="460" /><line x1="640" y1="0" x2="640" y2="460" />
              </g>
              <path d="M120,232 L210,232 L210,90 L320,90" stroke="#3f7d5a" strokeWidth="4" markerEnd="url(#mk-green2)" />
              <path d="M120,232 L320,232 L320,168" stroke="#b7bfba" strokeWidth="3" strokeDasharray="7 6" />
              <path d="M320,168 L390,140" stroke="#a23b2b" strokeWidth="4.5" />
              <path d="M300,300 L430,300 L430,90 L640,90" stroke="#1f6f8b" strokeWidth="4" strokeDasharray="9 6" markerEnd="url(#mk-blue2)" />
              <path d="M500,300 L640,300 L640,368" stroke="#a85f12" strokeWidth="4" strokeDasharray="9 6" markerEnd="url(#mk-amber2)" />
            </svg>
            <div style={css("position:absolute;left:70px;top:210px;display:flex;align-items:center;gap:8px;background:#16323b;color:#f4f6f5;border-radius:9px;padding:8px 11px;box-shadow:0 2px 6px rgba(16,32,37,.22)")}>
              <span className="mono" style={css("font-size:12px;font-weight:700;letter-spacing:.06em")}>HUB</span>
              <span className="mono" style={css("font-size:11px;color:#9fb0b6")}>Food-bank</span>
            </div>
            <Stop left={296} top={56} n="01" border="#c4ddce" accent="#3f7d5a" title={s.a01.title} sub={s.a01.sub} subColor="#3f7d5a" />
            <Stop left={612} top={56} n="02" border="#bcdae2" accent="#1f6f8b" title={s.a02.title} sub={s.a02.sub} subColor="#1f6f8b" />
            <Stop left={612} top={380} n="03" border="#e6cfa4" accent="#a85f12" title={s.a03.title} sub={s.a03.sub} subColor="#a85f12" />
            <Stop left={392} top={380} n="04" border="#d5d8d2" accent="#5c6b71" title={s.a04.title} sub={s.a04.sub} subColor="#43555c" />
            <Stop left={150} top={380} n="05" border="#d5d8d2" accent="#5c6b71" title={s.a05.title} sub={s.a05.sub} subColor="#43555c" />
            <div style={css("position:absolute;left:300px;top:140px;display:flex;flex-direction:column;align-items:flex-start;gap:3px")}>
              <div style={css("display:flex;align-items:center;gap:6px;background:#f3e5e1;border:2px solid #a23b2b;border-radius:9px;padding:6px 9px;box-shadow:0 2px 6px rgba(162,59,43,.25)")}>
                <span style={css("font-size:13px")}>✕</span>
                <span className="mono" style={css("font-size:12px;font-weight:700;color:#a23b2b")}>{v.t1.label}</span>
              </div>
              <span className="mono" style={css("font-size:11px;font-weight:600;color:#a23b2b;background:#fff;border:1px solid #e3c3ba;border-radius:5px;padding:2px 6px")}>{v.t1.status}</span>
            </div>
            <div style={css("position:absolute;left:262px;top:288px;display:flex;flex-direction:column;align-items:flex-start;gap:3px")}>
              <div style={css("display:flex;align-items:center;gap:6px;background:#e0eef1;border:2px solid #1f6f8b;border-radius:9px;padding:6px 9px;box-shadow:0 2px 6px rgba(31,111,139,.25)")}>
                <span className="mono" style={css("font-size:12px;font-weight:700;color:#1f6f8b")}>{v.t2.label}</span>
              </div>
              <span className="mono" style={css("font-size:11px;font-weight:600;color:#16536a;background:#fff;border:1px solid #bcdae2;border-radius:5px;padding:2px 6px")}>{v.t2.status}</span>
            </div>
            <div style={css("position:absolute;left:466px;top:288px;display:flex;flex-direction:column;align-items:flex-start;gap:3px")}>
              <div style={css("display:flex;align-items:center;gap:6px;background:#f6ebd9;border:2px dashed #a85f12;border-radius:9px;padding:6px 9px")}>
                <span className="mono" style={css("font-size:12px;font-weight:700;color:#a85f12")}>{v.part.label}</span>
              </div>
              <span className="mono" style={css("font-size:11px;font-weight:600;color:#8a6a1f;background:#fff;border:1px solid #e6cfa4;border-radius:5px;padding:2px 6px")}>{v.part.status}</span>
            </div>
          </div>
          <div style={css("display:flex;flex-wrap:wrap;gap:14px;margin-top:12px;padding-top:12px;border-top:1px solid #dbe1dc")}>
            <Legend swatch="height:4px;background:#3f7d5a" label="Completed (O201)" />
            <Legend swatch="height:4px;background:#a23b2b" label="Failed segment" />
            <Legend swatch="border-top:3px dashed #1f6f8b" label="Truck 2 recovery" />
            <Legend swatch="border-top:3px dashed #a85f12" label="Partner pickup" />
          </div>
        </div>
        <div style={css("display:flex;flex-direction:column;gap:14px")}>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:13px")}>TRUCK 2 CAPACITY DECISION</div>
            <div style={css("display:flex;flex-direction:column;gap:9px")}>
              <CapRow label={cap.beforeLabel} value={cap.beforeValue} />
              <CapRow label={cap.addLabel} value={cap.addValue} valueColor="#1f6f8b" />
              <div style={css("height:16px;border-radius:5px;background:#e9ece9;overflow:hidden")}>
                <div style={css(`width:${cap.afterFillPct}%;height:100%;background:#1f6f8b`)} />
              </div>
              <CapRow label={cap.afterLabel} value={cap.afterValue} valueColor="#1f6f8b" pt />
              <CapRow label={cap.remainingLabel} value={cap.remainingValue} />
              <div style={css("display:flex;justify-content:space-between;align-items:center;padding-bottom:6px;border-bottom:1px solid #eceee9")}>
                <span style={css("font-size:13px;color:#43555c")}>{cap.needsLabel}</span>
                <span className="mono" style={css("font-size:14px;font-weight:600")}>{cap.needsValue}</span>
              </div>
            </div>
            <div style={css("background:#f3e5e1;border:1px solid #e3c3ba;border-radius:8px;padding:10px 12px;text-align:center;margin-top:12px")}>
              <span className="mono" style={css("font-size:13px;font-weight:700;letter-spacing:.04em;color:#a23b2b")}>{cap.verdict}</span>
            </div>
            <div style={css("font-size:12px;color:#43555c;line-height:1.5;margin-top:11px")}>{cap.explain}</div>
          </div>
          <div style={css("background:#16323b;border-radius:10px;padding:16px;color:#f4f6f5")}>
            <div style={css("font-size:12px;color:#c8d5d8;line-height:1.45;margin-bottom:12px")}>This schematic shows how the 42-case recovery load reassigns without exceeding capacity. It is not where the change is approved.</div>
            <span role="button" tabIndex={0} className="fs-btn-teal" onClick={() => onGo("revisionReview")} onKeyDown={(e) => e.key === "Enter" && onGo("revisionReview")} style={css("display:block;text-align:center;background:#1f6f8b;color:#fff;border-radius:7px;padding:11px;font-size:14px;font-weight:600;cursor:pointer")}>← Return to plan revision</span>
          </div>
        </div>
      </div>
    </>
  );
}

function Stop({ left, top, n, border, accent, title, sub, subColor }: { left: number; top: number; n: string; border: string; accent: string; title: string; sub: string; subColor: string }) {
  return (
    <div style={css(`position:absolute;left:${left}px;top:${top}px;display:flex;align-items:center;gap:7px;background:#fff;border:1px solid ${border};border-left:4px solid ${accent};border-radius:9px;padding:7px 10px;box-shadow:0 1px 4px rgba(16,32,37,.12)`)}>
      <span className="mono" style={css(`width:19px;height:19px;border-radius:50%;background:${accent};color:#fff;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center`)}>{n}</span>
      <div>
        <div style={css("font-size:12px;font-weight:600")}>{title}</div>
        <div className="mono" style={css(`font-size:11px;color:${subColor}`)}>{sub}</div>
      </div>
    </div>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <div style={css("display:flex;align-items:center;gap:7px")}>
      <span style={css(`width:22px;border-radius:2px;${swatch}`)} />
      <span style={css("font-size:12px;color:#43555c")}>{label}</span>
    </div>
  );
}

function CapRow({ label, value, valueColor, pt }: { label: string; value: string; valueColor?: string; pt?: boolean }) {
  return (
    <div style={css(`display:flex;justify-content:space-between;align-items:center${pt ? ";padding-top:2px" : ""}`)}>
      <span style={css("font-size:13px;color:#43555c")}>{label}</span>
      <span className="mono" style={css(`font-size:14px;font-weight:600${valueColor ? `;color:${valueColor}` : ""}`)}>{value}</span>
    </div>
  );
}
