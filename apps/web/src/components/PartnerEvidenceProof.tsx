import { css } from "../styles/css";
import type { PartnerEvidenceProofView } from "../types/fullShelf";

export function PartnerEvidenceProof({ proof }: { proof: PartnerEvidenceProofView }) {
  const applied = proof.decision === "APPLIED";
  const claims = Object.entries(proof.claims);
  return (
    <section
      data-testid={`partner-evidence-${applied ? "complete" : "vague"}`}
      style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;overflow:hidden")}
    >
      <div style={css(`padding:14px 18px;border-left:5px solid ${applied ? "#3f7d5a" : "#a85f12"};background:${applied ? "#e8f2ea" : "#f8eedc"}`)}>
        <div className="mono" style={css("font-size:10px;letter-spacing:.1em;color:#5d6c70;font-weight:700")}>ISOLATED SELECTED PROOF · DOES NOT REWRITE THE CANONICAL FILMED TIMELINE</div>
        <div style={css("display:flex;justify-content:space-between;gap:16px;margin-top:6px") }>
          <strong style={css("font-size:16px;color:#16323b")}>{applied ? "Complete partner response" : "Vague partner response"}</strong>
          <span className="mono" style={css(`font-size:11px;font-weight:700;color:${applied ? "#2e6948" : "#8a5a12"}`)}>{proof.decision}</span>
        </div>
      </div>

      <div style={css("display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:18px;padding:18px") }>
        <div>
          <div className="mono" style={css("font-size:10px;letter-spacing:.09em;color:#74848a;margin-bottom:7px")}>AUTHENTICATED SOURCE RESPONSE</div>
          <blockquote style={css("margin:0;background:#f6f5f1;border:1px solid #e5e4de;border-radius:7px;padding:12px 14px;font-size:13px;line-height:1.55;color:#243940")}>{proof.originalResponse}</blockquote>
          <div style={css("font-size:11px;color:#617177;margin-top:8px;line-height:1.5") }>
            {proof.partnerId} · occurred {proof.sourceOccurredAt} · received {proof.receivedAt}<br />
            {proof.callbackPrincipal.provenance} · {proof.callbackPrincipal.email}
          </div>
          <div style={css("margin-top:10px;font-size:11px;line-height:1.5;color:#43575d") }>
            Model Armor · {proof.modelArmorStatus}<br />
            Partner Operations · {proof.proposalRationale ?? "No advisory rationale emitted"}
          </div>

          <div className="mono" style={css("font-size:10px;letter-spacing:.09em;color:#74848a;margin:18px 0 8px")}>CLAIM ANCHORS</div>
          <div style={css("display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px") }>
            {claims.map(([name, claim]) => (
              <div key={name} style={css("border:1px solid #e1e4df;border-radius:6px;padding:8px 10px") }>
                <div style={css("font-size:11px;font-weight:600;color:#34494f;text-transform:capitalize")}>{name.replace(/_/g, " ")}</div>
                <div className="mono" style={css(`font-size:10px;margin-top:3px;color:${claim.state === "PRESENT" ? "#3f7d5a" : claim.state === "MISSING" ? "#a85f12" : "#a23b2b"}`)}>{claim.state} · {claim.reason}</div>
              </div>
            ))}
          </div>
        </div>

        <aside style={css("background:#16323b;color:#eaf0f0;border-radius:8px;padding:14px 15px") }>
          <div className="mono" style={css("font-size:10px;letter-spacing:.09em;color:#8fc6da")}>DETERMINISTIC POLICY + LEDGER</div>
          <dl style={css("display:grid;grid-template-columns:1fr auto;gap:8px 12px;margin:13px 0;font-size:12px") }>
            <dt>Receipt</dt><dd className="mono" style={css("margin:0")}>{proof.receiptId ?? "—"}</dd>
            <dt>Domain mutations</dt><dd className="mono" style={css("margin:0")}>{proof.domainMutationsApplied}</dd>
            <dt>Evidence mutations</dt><dd className="mono" style={css("margin:0")}>{proof.evidenceMutationsApplied}</dd>
            <dt>Custody</dt><dd className="mono" style={css("margin:0")}>{proof.confirmedCasesBefore ?? "—"}/{proof.totalCases ?? "—"} → {proof.confirmedCasesAfter ?? "—"}/{proof.totalCases ?? "—"}</dd>
            <dt>Work item</dt><dd className="mono" style={css("margin:0")}>{proof.workItemBefore ?? "—"} → {proof.workItemAfter ?? "—"}</dd>
          </dl>
          {proof.reasons.length ? (
            <div style={css("border-top:1px solid #31505a;padding-top:10px;font-size:11px;line-height:1.5;color:#f0c987")}>{proof.reasons.join(" · ")}</div>
          ) : null}
          <div style={css("border-top:1px solid #31505a;margin-top:10px;padding-top:10px;font-size:10px;line-height:1.5;color:#a9bcc2") }>
            {proof.agentId}<br />{proof.modelId} · {proof.adkFramework}<br />
            session {proof.adkSessionId ?? "—"}<br />invocation {proof.adkInvocationId ?? "—"}<br />event {proof.adkEventId ?? "—"}
          </div>
        </aside>
      </div>
    </section>
  );
}
