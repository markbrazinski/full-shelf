import { css } from "../styles/css";
import { TONE } from "../styles/tokens";
import type { GovernanceView } from "../types/fullShelf";

export function GovernanceRefusal({ governance, onOpenEvidence }: { governance: GovernanceView; onOpenEvidence: () => void }) {
  const r = governance.refusal;
  return (
    <>
      <div style={css("margin-bottom:14px")}>
        <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#74848a;font-weight:600")}>GOVERNANCE · A REFUSED PROPOSAL</div>
        <h1 style={css("font-size:24px;font-weight:600;letter-spacing:-.01em;margin-top:5px")}>{governance.question}</h1>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 340px;gap:18px;align-items:start")}>
        <div style={css("display:flex;flex-direction:column;gap:14px")}>
          <div style={css("background:#fff;border:1px solid #bcdae2;border-left:4px solid #1f6f8b;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#1f6f8b;font-weight:600;margin-bottom:8px")}>◆ {governance.proposal.label}</div>
            <div style={css("font-size:13px;color:#2b3b41;line-height:1.5")}>{governance.proposal.text}</div>
          </div>
          <div style={css("display:flex;align-items:center;gap:10px;padding-left:6px")}>
            <span className="mono" style={css("font-size:16px;color:#74848a")}>↓</span>
            <span className="mono" style={css("font-size:11px;letter-spacing:.06em;color:#74848a;font-weight:600")}>{governance.policyEvalLabel}</span>
          </div>
          <div style={css("background:#2a1512;border:1px solid #5a2a20;border-radius:10px;padding:16px 18px")}>
            <div style={css("display:flex;align-items:center;justify-content:space-between;margin-bottom:10px")}>
              <div style={css("display:flex;align-items:center;gap:9px")}>
                <span className="mono" style={css("font-size:16px;color:#e88f7c")}>■</span>
                <span className="mono" style={css("font-size:14px;font-weight:700;letter-spacing:.06em;color:#f0b3a5")}>{r.verdict}</span>
              </div>
              <span role="button" tabIndex={0} onClick={onOpenEvidence} onKeyDown={(e) => e.key === "Enter" && onOpenEvidence()} style={css("font-size:12px;color:#e6a99e;cursor:pointer;font-weight:600")}>Record →</span>
            </div>
            <div style={css("font-size:13px;color:#e6cec8;line-height:1.55")}>{r.body}</div>
            <div style={css("display:flex;gap:18px;margin-top:13px;padding-top:12px;border-top:1px solid #4a241c")}>
              <Fact label="REASON" value={r.reason} />
              <Fact label="MUTATIONS" value={r.mutations} mono />
              <Fact label="RECORDED" value={r.recordedAt} mono />
            </div>
          </div>
          <div style={css("font-size:12px;color:#74848a;line-height:1.5;padding:0 4px")}>{governance.policyNote}</div>
        </div>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:15px 16px")}>
          <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:11px")}>WHY IT CANNOT CLOSE</div>
          <div style={css("display:flex;flex-direction:column;gap:9px")}>
            {governance.whyCannotClose.map((w, i) => {
              const t = TONE[w.tone];
              return (
                <div key={i} style={css(`display:flex;justify-content:space-between;align-items:center;padding:9px 11px;background:${t.bg};border:1px solid ${t.border};border-radius:7px`)}>
                  <span style={css(`font-size:12px;color:${t.fg}`)}>{w.label}</span>
                  <span className="mono" style={css(`font-size:13px;font-weight:600;color:${t.accent}`)}>{w.value}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="mono" style={css("font-size:11px;color:#9c6d64")}>{label}</div>
      <div className={mono ? "mono" : undefined} style={css("font-size:12px;color:#e6cec8;margin-top:2px")}>{value}</div>
    </div>
  );
}
