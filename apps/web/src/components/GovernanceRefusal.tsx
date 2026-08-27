import { css } from "../styles/css";
import { facilityName } from "../data/contract/facilityNames";
import { TONE } from "../styles/tokens";
import type { GovernanceView } from "../types/fullShelf";

export function GovernanceRefusal({ governance, onOpenEvidence }: { governance: GovernanceView; onOpenEvidence: () => void }) {
  const r = governance.refusal;
  return (
    <>
      <div style={css("margin-bottom:14px")}>
        <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#74848a;font-weight:600")}>CLOSURE BLOCKED</div>
        <h1 style={css("font-size:24px;font-weight:600;letter-spacing:-.01em;margin-top:5px;color:#16323b")}>{"Closure refused — 8 cases remain unconfirmed"}</h1>
        <div style={css("font-size:13px;color:#5c6b71;margin-top:5px;line-height:1.5")}>Full containment cannot be asserted without custody confirmation. The refusal is not a rejection — it is the necessary consequence of incomplete information.</div>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 340px;gap:18px;align-items:start")}>
        <div style={css("display:flex;flex-direction:column;gap:14px")}>
          <div style={css("background:#f9f4f0;border:1px solid #e3c3ba;border-left:4px solid #a23b2b;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#a23b2b;font-weight:600;margin-bottom:8px")}>1. RECOVERY ACTIONS RECONCILED</div>
            <div style={css("font-size:13px;color:#2b3b41;line-height:1.5")}>{governance.proposal.text}</div>
          </div>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:8px")}>2. CLOSURE ELIGIBILITY CHECK REQUESTED</div>
            <div style={css("font-size:13px;color:#2b3b41;line-height:1.5")}>{governance.policyEvalLabel}</div>
          </div>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:8px")}>3. EIGHT SITE 01 CASES REMAIN UNCONFIRMED</div>
            <div style={css("font-size:13px;color:#2b3b41;line-height:1.5;margin-bottom:8px")}>{r.body}</div>
            <div style={css("font-size:12px;color:#74848a;line-height:1.5")}>{governance.policyNote}</div>
          </div>
          <div style={css("background:#2a1512;border:1px solid #5a2a20;border-radius:10px;padding:16px 18px")}>
            <div style={css("display:flex;align-items:center;justify-content:space-between;margin-bottom:10px")}>
              <div style={css("display:flex;align-items:center;gap:9px;flex:1")}>
                <span className="mono" style={css("font-size:14px;font-weight:700;letter-spacing:.06em;color:#f0b3a5")}>4. DETERMINISTIC POLICY BLOCKS CLOSURE</span>
              </div>
              <span role="button" tabIndex={0} onClick={onOpenEvidence} onKeyDown={(e) => e.key === "Enter" && onOpenEvidence()} style={css("font-size:12px;color:#e6a99e;cursor:pointer;font-weight:600;flex:none")}>Record →</span>
            </div>
            <div style={css("display:flex;gap:18px;margin-top:8px;padding:10px 0;border-top:1px solid #4a241c;border-bottom:1px solid #4a241c")}>
              <Fact label="VERDICT" value={r.verdict} mono />
              <Fact label="MUTATIONS" value={r.mutations} mono />
              <Fact label="RECORDED" value={r.recordedAt} mono />
            </div>
            <div style={css("margin-top:8px")}>
              <div className="mono" style={css("font-size:11px;letter-spacing:.06em;color:#e6cec8")}>5. INCIDENT REMAINS {r.posture}</div>
              <div className="mono" style={css("font-size:11px;color:#cdb5ae;margin-top:6px;line-height:1.5")}>{`Movement barrier and ${facilityName("SITE-01")} work item remain active.`} Obligation carries into Saturday.</div>
            </div>
          </div>
        </div>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;overflow:hidden")}>
          <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;padding:13px 16px;border-bottom:1px solid #eceee9")}>CLOSURE BLOCKERS</div>
          <div style={css("display:flex;flex-direction:column")}>
            {governance.whyCannotClose.map((w, i) => {
              const t = TONE[w.tone];
              return (
                <div key={i} style={css(`display:flex;justify-content:space-between;align-items:center;padding:10px 16px;border-bottom:1px solid #f2f1ec;background:${t.bg}`)}>
                  <span style={css(`font-size:12px;color:${t.fg}`)}>{w.label}</span>
                  <span className="mono" style={css(`font-size:13px;font-weight:600;color:${t.accent}`)}>{w.value}</span>
                </div>
              );
            })}
          </div>
          <div className="mono" style={css("font-size:10px;color:#74848a;padding:9px 16px;background:#faf9f5;border-top:1px solid #eceee9")}>The policy is deterministic and carries no override.</div>
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
