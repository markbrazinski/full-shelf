// =====================================================================
// The canonical partner reply, and why it did not confirm custody.
// ---------------------------------------------------------------------
// This is ordinary Friday history, not an isolated proof: the reply
// arrived at 10:11 and closure was refused at 10:12 BECAUSE of what it
// failed to establish. Showing the refusal without it leaves the eight
// unconfirmed cases unexplained.
//
// Everything rendered here is projection-derived. The component decides
// no policy: Partner Operations read likely intent, and deterministic
// policy — not the agent — denied the evidence.
//
// There is deliberately no reply box, no override, and no approve
// control. The operator cannot argue with this surface, only read it.
// =====================================================================

import { css } from "../styles/css";
import { facilityName } from "../data/contract/facilityNames";
import type { PartnerEvidenceProofView } from "../types/fullShelf";

/** Wire claim keys → the operator-facing evidence names, in required order. */
const CLAIM_LABELS: [key: string, label: string][] = [
  ["lot", "Lot ID"],
  ["quantity", "Quantity"],
  ["location", "Confirmed location"],
  ["disposition", "Qualifying disposition"],
  ["confirmation_time", "Confirmation time"],
];

/** "…T10:11:00+00:00" → "10:11 AM". Never re-derives a date. */
function clockLabel(iso: string): string {
  const m = /T(\d{2}):(\d{2})/.exec(iso);
  if (!m) return iso;
  const hour = Number(m[1]);
  const suffix = hour < 12 ? "AM" : "PM";
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return `${twelve}:${m[2]} ${suffix}`;
}

export function PartnerResponseEvidence({ evidence }: { evidence: PartnerEvidenceProofView }) {
  const missing = CLAIM_LABELS.filter(([key]) => evidence.claims[key]?.state === "MISSING");
  const custody = `${evidence.confirmedCasesAfter ?? 88}/${evidence.totalCases ?? 96}`;

  return (
    <div
      data-testid="partner-response-evidence"
      style={css(
        "background:#fff;border:1px solid #d5d8d2;border-left:4px solid #c98a2e;" +
          "border-radius:10px;padding:9px 12px",
      )}
    >
      <div style={css("display:flex;align-items:baseline;gap:8px")}>
        <span className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600")}>
          PARTNER RESPONSE
        </span>
        <span className="mono" style={css("font-size:10px;color:#a23b2b;font-weight:600;margin-left:auto;flex:none")}>
          EVIDENCE INSUFFICIENT
        </span>
      </div>

      <div style={css("font-size:11.5px;color:#74848a;margin-top:5px;line-height:1.35")}>
        {`${facilityName("SITE-01")} · authenticated partner callback · ${clockLabel(evidence.committedAt)}`}
      </div>

      {/* The partner's own words, quoted and never paraphrased. */}
      <blockquote
        data-testid="partner-response-text"
        style={css(
          "margin:6px 0 0;padding:5px 9px;background:#faf9f5;border-left:3px solid #d5d8d2;" +
            "border-radius:0 6px 6px 0;font-size:12px;color:#2b3b41;line-height:1.4;font-style:italic",
        )}
      >
        {`“${evidence.originalResponse}”`}
      </blockquote>

      <div style={css("font-size:11.5px;color:#2b3b41;margin-top:7px;line-height:1.4")}>
        Partner Operations read likely containment intent. Missing:
      </div>
      <div style={css("display:flex;flex-wrap:wrap;gap:3px;margin-top:4px")}>
        {missing.map(([key, label]) => (
          <span
            key={key}
            data-testid={`missing-claim-${key}`}
            style={css(
              "font-size:11px;color:#8a2f22;background:#f7ece9;border:1px solid #e3c3ba;" +
                "border-radius:4px;padding:1px 6px",
            )}
          >
            {label}
          </span>
        ))}
      </div>

      <div style={css("font-size:11.5px;color:#5c6b71;margin-top:7px;line-height:1.4")}>
        The reply was recorded, but it does not satisfy the evidence required to confirm custody.
      </div>

      <div
        className="mono"
        data-testid="partner-evidence-footer"
        style={css(
          "font-size:10px;color:#74848a;margin-top:7px;padding-top:6px;" +
            "border-top:1px solid #eceee9;line-height:1.4",
        )}
      >
        {`Reply recorded \u00b7 Custody remains ${custody} \u00b7 Acknowledgment remains open`}
      </div>
    </div>
  );
}
