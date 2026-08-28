import { css } from "../styles/css";
import { facilityName } from "../data/contract/facilityNames";
import { TONE } from "../styles/tokens";
import { PartnerResponseEvidence } from "./PartnerResponseEvidence";
import type { GovernanceView, PartnerEvidenceProofView } from "../types/fullShelf";

export function GovernanceRefusal({
  governance,
  partnerEvidence,
  onOpenEvidence,
}: {
  governance: GovernanceView;
  /** The canonical reply that failed to confirm custody, if one committed. */
  partnerEvidence?: PartnerEvidenceProofView;
  onOpenEvidence: () => void;
}) {
  const r = governance.refusal;
  return (
    <>
      <div style={css("margin-bottom:10px")}>
        <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#74848a;font-weight:600")}>CLOSURE BLOCKED</div>
        <h1 style={css("font-size:22px;font-weight:600;letter-spacing:-.01em;margin-top:4px;color:#16323b")}>{"Closure refused — 8 cases remain unconfirmed"}</h1>
        <div style={css("font-size:13px;color:#5c6b71;margin-top:5px;line-height:1.5")}>
          {partnerEvidence
            ? `Eight cases at ${facilityName("SITE-01")} remain unconfirmed because the partner response does not satisfy the custody evidence requirement.`
            : "Full containment cannot be asserted without custody confirmation. The refusal is not a rejection — it is the necessary consequence of incomplete information."}
        </div>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 340px;gap:14px;align-items:start")}>
        <div style={css("display:flex;flex-direction:column;gap:8px")}>
          <div style={css("background:#f9f4f0;border:1px solid #e3c3ba;border-left:4px solid #a23b2b;border-radius:10px;padding:10px 13px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#a23b2b;font-weight:600;margin-bottom:8px")}>1. RECOVERY ACTIONS RECONCILED</div>
            <div style={css("font-size:12.5px;color:#2b3b41;line-height:1.45")}>{governance.proposal.text}</div>
          </div>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:10px 13px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:8px")}>2. CLOSURE ELIGIBILITY CHECK REQUESTED</div>
            <div style={css("font-size:12.5px;color:#2b3b41;line-height:1.45")}>{governance.policyEvalLabel}</div>
          </div>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:10px 13px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:8px")}>{`3. EIGHT ${facilityName("SITE-01").toUpperCase()} CASES REMAIN UNCONFIRMED`}</div>
            <div style={css("font-size:12.5px;color:#2b3b41;line-height:1.45;margin-bottom:6px")}>{r.body}</div>
            <div style={css("font-size:12px;color:#74848a;line-height:1.5")}>{governance.policyNote}</div>
          </div>
          {/* Why those eight cases are still unconfirmed. Adjacent to the
              refusal so the reason needs no second surface. */}
          {partnerEvidence ? <PartnerResponseEvidence evidence={partnerEvidence} /> : null}
        </div>
        <div style={css("display:flex;flex-direction:column;gap:12px")}>
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

        {/* The governance verdict sits directly beneath the blockers so it
            is legible at 1600x900 without scrolling — it is the evidence
            that the refusal changed nothing. */}
        <div
          data-testid="refusal-verdict"
          style={css("background:#2a1512;border:1px solid #5a2a20;border-radius:10px;padding:11px 14px")}
        >
          <div style={css("display:flex;align-items:center;gap:9px")}>
            <span className="mono" style={css("font-size:12px;font-weight:700;letter-spacing:.06em;color:#f0b3a5")}>
              DETERMINISTIC POLICY BLOCKS CLOSURE
            </span>
            <span
              role="button"
              tabIndex={0}
              onClick={onOpenEvidence}
              onKeyDown={(e) => e.key === "Enter" && onOpenEvidence()}
              style={css("font-size:11.5px;color:#e6a99e;cursor:pointer;font-weight:600;margin-left:auto;flex:none")}
            >
              Record →
            </span>
          </div>
          <div style={css("display:flex;gap:16px;margin-top:7px;padding:7px 0;border-top:1px solid #4a241c;border-bottom:1px solid #4a241c")}>
            <Fact label="VERDICT" value={r.verdict} mono />
            <Fact label="MUTATIONS" value={r.mutations} mono />
            <Fact label="RECORDED" value={r.recordedAt} mono />
          </div>
          <div className="mono" style={css("font-size:10.5px;letter-spacing:.05em;color:#e6cec8;margin-top:7px")}>
            INCIDENT REMAINS {r.posture}
          </div>
          <div className="mono" style={css("font-size:10px;color:#cdb5ae;margin-top:4px;line-height:1.45")}>
            {`Barrier and ${facilityName("SITE-01")} work item remain active; obligations carry into Saturday.`}
          </div>
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
