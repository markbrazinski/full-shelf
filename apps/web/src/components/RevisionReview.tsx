import { css } from "../styles/css";
import type { BeatId, IncidentView } from "../types/fullShelf";

interface Props {
  incident: IncidentView;
  onToday: () => void;
  onGo: (b: BeatId) => void;
  onApprove: () => void;
}

export function RevisionReview({ incident, onToday, onGo, onApprove }: Props) {
  // Model reasoning is not persisted by the contract, so the advisory
  // panel is omitted rather than filled with invented prose.
  const r = incident.rationale;
  const cta = incident.approvalCta;
  return (
    <>
      <div style={css("display:flex;align-items:center;gap:10px;margin-bottom:14px")}>
        <span role="button" tabIndex={0} onClick={onToday} onKeyDown={(e) => e.key === "Enter" && onToday()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>← Today</span>
        <span className="mono" style={css("font-size:11px;color:#93a1a6")}>/</span>
        <span className="mono" style={css("font-size:12px;color:#74848a;letter-spacing:.02em")}>Incident {incident.ref} · Proposed plan revision</span>
      </div>
      <div style={css("display:flex;align-items:center;gap:14px;background:#f6ebd9;border:1px solid #e6cfa4;border-left:4px solid #a85f12;border-radius:9px;padding:13px 16px;margin-bottom:16px")}>
        <span className="mono" style={css("font-size:18px;color:#a85f12")}>▲</span>
        <div style={css("flex:1")}>
          <div style={css("font-size:14px;font-weight:600;color:#8a6a1f")}>{incident.banner.title}</div>
          <div style={css("font-size:12px;color:#8a6a1f;margin-top:1px")}>{incident.banner.body}</div>
        </div>
        <span role="button" tabIndex={0} onClick={() => onGo("dispatchSchematic")} onKeyDown={(e) => e.key === "Enter" && onGo("dispatchSchematic")} style={css("font-size:12px;font-weight:600;background:#16323b;color:#f4f6f5;padding:8px 14px;border-radius:6px;cursor:pointer;white-space:nowrap")}>◆ View dispatch schematic →</span>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 360px;gap:18px;align-items:start")}>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;overflow:hidden")}>
          <div style={css("padding:14px 18px;border-bottom:1px solid #eceee9;display:flex;align-items:center;justify-content:space-between;background:#f0f4f5")}>
            <div style={css("display:flex;align-items:center;gap:10px")}>
              <span style={css("font-size:15px;font-weight:600")}>Proposed plan revision</span>
              <span className="mono" style={css("font-size:13px;font-weight:600;color:#1a2a30")}>rev07 → rev08</span>
            </div>
            <span className="mono" style={css("font-size:11px;font-weight:600;padding:4px 10px;border-radius:5px;background:#e0eef1;color:#1f6f8b;border:1px solid #bcdae2")}>◆ ADVISORY PROPOSAL</span>
          </div>
          <div style={css("padding:8px 18px 16px")}>
            {(incident.diffRows ?? []).map((d) => (
              <div key={d.id} style={css("border:1px solid #eceee9;border-radius:8px;padding:12px 14px;margin-top:12px")}>
                <div style={css("display:flex;align-items:center;gap:10px;margin-bottom:9px")}>
                  <span className="mono" style={css("font-size:13px;font-weight:600")}>{d.id}</span>
                  <span style={css("font-size:12px;color:#43555c")}>{d.meta}</span>
                  <span className="mono" style={css("margin-left:auto;font-size:11px;font-weight:600;padding:2px 7px;border-radius:4px;background:#f6ebd9;color:#a85f12")}>CHANGED</span>
                </div>
                <div style={css("display:flex;align-items:center;gap:12px")}>
                  <div style={css("flex:1;background:#f5f3ee;border:1px solid #e5e2d8;border-radius:6px;padding:8px 11px")}>
                    <div className="mono" style={css("font-size:10px;letter-spacing:.08em;color:#9aa4a7")}>BEFORE · rev07</div>
                    <div style={css("font-size:13px;text-decoration:line-through;text-decoration-color:#c08a4a;color:#74848a;margin-top:2px")}>{d.before}</div>
                  </div>
                  <span style={css("color:#a85f12;font-weight:700")}>→</span>
                  <div style={css("flex:1;background:#e0eef1;border:1px solid #bcdae2;border-radius:6px;padding:8px 11px")}>
                    <div className="mono" style={css("font-size:10px;letter-spacing:.08em;color:#1f6f8b")}>AFTER · rev08</div>
                    <div style={css("font-size:13px;font-weight:600;color:#16323b;margin-top:2px")}>{d.after}</div>
                  </div>
                </div>
              </div>
            ))}
            <div style={css("margin-top:12px;padding:10px 13px;background:#faf9f5;border:1px dashed #d5d8d2;border-radius:7px;font-size:12px;color:#43555c")}>{incident.unaffectedNote}</div>
          </div>
        </div>
        <div style={css("display:flex;flex-direction:column;gap:14px")}>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:12px")}>WHY THIS RECOVERY <span style={css("color:#1f6f8b")}>· ADVISORY</span></div>
            {r ? (
              <>
                <Section title="OBSERVATION" color="#1f6f8b" body={r.observation} />
                <Section title="CONSTRAINTS" color="#a85f12" body={r.constraints} />
                <Section title="FEASIBLE OPTION" color="#3f7d5a" body={r.feasibleOption} />
                <Section title="REQUIRED AUTHORITY" color="#16323b" body={r.requiredAuthority} last />
              </>
            ) : (
              <div style={css("font-size:12px;color:#74848a;line-height:1.5")}>
                No agent rationale was persisted for this revision, so none is shown. The committed plan diff below is the authoritative record.
              </div>
            )}
          </div>
          <div style={css("background:#16323b;border-radius:10px;padding:16px 16px 15px;color:#f4f6f5")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#f0c987;font-weight:600;margin-bottom:4px")}>▲ HUMAN APPROVAL REQUIRED</div>
            <div style={css("font-size:12px;color:#c8d5d8;line-height:1.4;margin-bottom:13px")}>{cta?.guard ?? "This revision requires verified human approval."}</div>
            <button type="button" className="fs-btn-teal" onClick={onApprove} style={css("width:100%;background:#1f6f8b;color:#fff;border:none;border-radius:7px;padding:12px;font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 0 0 3px rgba(31,111,139,.22);font-family:'IBM Plex Sans',sans-serif")}>{cta?.label ?? "Approve revision"}</button>
            <div style={css("font-size:11px;color:#a4b4ba;text-align:center;margin-top:9px")}>Approves the complete diff as a single change</div>
          </div>
        </div>
      </div>
    </>
  );
}

function Section({ title, color, body, last }: { title: string; color: string; body: string; last?: boolean }) {
  return (
    <div style={css(last ? "" : "margin-bottom:12px")}>
      <div className="mono" style={css(`font-size:11px;color:${color};font-weight:600;margin-bottom:3px`)}>{title}</div>
      <div style={css("font-size:12px;color:#2b3b41;line-height:1.45")}>{body}</div>
    </div>
  );
}
