// =====================================================================
// Full Shelf — isolated proof branches
// ---------------------------------------------------------------------
// Two selected proofs, entered and exited through the REAL runtime
// endpoints (`POST …/branch`, `DELETE …/branch`). Nothing here is staged
// locally: the custody figures, decision, reasons and mutation counts all
// come from the branch projection the runtime returns.
//
// Available only from event 22 — before that the runtime answers
// `409 PROOF_BRANCH_NOT_AVAILABLE_YET`, and the controls stay disabled.
//
// Entering a branch does not move the canonical cursor, feed, receipts or
// projection. Exiting restores canonical 88/96 and PARTIALLY_CONTAINED,
// byte-identical. Branch state is labelled ISOLATED SELECTED PROOF so it
// can never read as canonical truth.
// =====================================================================

import { css } from "../styles/css";
import type { PartnerEvidenceProofView } from "../types/fullShelf";

export type BranchKind = "vague" | "complete";

interface Props {
  available: boolean;
  active: BranchKind | null;
  busy: boolean;
  proofLabel: string | null;
  evidence?: PartnerEvidenceProofView;
  custody: { total: number; confirmed: number; unconfirmed: number } | null;
  onEnter: (kind: BranchKind) => void;
  onExit: () => void;
}

export function EvidenceBranchPanel({
  available,
  active,
  busy,
  proofLabel,
  evidence,
  custody,
  onEnter,
  onExit,
}: Props) {
  const denied = evidence?.decision === "DENIED";

  return (
    <section
      data-testid="evidence-branch-panel"
      data-branch={active ?? "canonical"}
      style={css(
        `background:#fff;border:1px solid ${active ? "#8f7fb8" : "#d5d8d2"};` +
          `${active ? "border-left:5px solid #6f5da0;" : ""}border-radius:11px;overflow:hidden`,
      )}
    >
      <div
        style={css(
          "padding:12px 16px;border-bottom:1px solid #eceee9;background:#faf9f5;" +
            "display:flex;align-items:center;gap:11px;flex-wrap:wrap",
        )}
      >
        <div style={css("flex:1;min-width:220px")}>
          <div className="mono" style={css("font-size:10px;letter-spacing:.1em;color:#74848a;font-weight:700")}>
            SELECTED PROOF · PARTNER CUSTODY EVIDENCE
          </div>
          <div style={css("font-size:12px;color:#5c6b71;margin-top:4px;line-height:1.5")}>
            {available
              ? "Run either evidence branch in isolation. Canonical state is untouched and restored on exit."
              : "Available from the canonical terminal state. The runtime refuses a branch before then."}
          </div>
        </div>

        {active ? (
          <span
            className="mono"
            data-testid="branch-authority-label"
            style={css(
              "font-size:9px;font-weight:700;letter-spacing:.07em;color:#4c3f73;" +
                "background:#ece7f5;border:1px solid #c3b7dd;border-radius:5px;padding:5px 9px",
            )}
          >
            ◆ {proofLabel ?? "ISOLATED SELECTED PROOF"}
          </span>
        ) : (
          <span
            className="mono"
            data-testid="branch-authority-label"
            style={css(
              "font-size:9px;font-weight:700;letter-spacing:.07em;color:#3f7d5a;" +
                "background:#e5efe9;border:1px solid #c4ddce;border-radius:5px;padding:5px 9px",
            )}
          >
            ● CANONICAL
          </span>
        )}
      </div>

      <div style={css("padding:12px 16px;display:flex;align-items:center;gap:9px;flex-wrap:wrap")}>
        <BranchButton
          testId="branch-enter-vague"
          label="Vague evidence"
          active={active === "vague"}
          disabled={!available || busy || active === "complete"}
          onClick={() => onEnter("vague")}
        />
        <BranchButton
          testId="branch-enter-complete"
          label="Complete evidence"
          active={active === "complete"}
          disabled={!available || busy || active === "vague"}
          onClick={() => onEnter("complete")}
        />
        <button
          type="button"
          data-testid="branch-exit"
          onClick={onExit}
          disabled={!active || busy}
          style={css(
            `background:${active && !busy ? "#16323b" : "#e2e6df"};color:${active && !busy ? "#eef4f4" : "#8d9a9f"};` +
              "border:none;border-radius:7px;padding:8px 15px;font-size:12px;font-weight:600;" +
              `cursor:${active && !busy ? "pointer" : "not-allowed"}`,
          )}
        >
          Return to canonical
        </button>
      </div>

      {custody ? (
        <div
          data-testid="branch-custody"
          data-confirmed={String(custody.confirmed)}
          data-total={String(custody.total)}
          style={css(
            "padding:12px 16px;border-top:1px solid #eceee9;display:flex;align-items:center;gap:18px;flex-wrap:wrap;" +
              `background:${active ? "#f7f5fb" : "#fff"}`,
          )}
        >
          <div>
            <div className="mono" style={css("font-size:9px;letter-spacing:.1em;color:#74848a;font-weight:700")}>
              CONFIRMED CUSTODY
            </div>
            <div
              className="mono"
              data-testid="branch-custody-figure"
              style={css(
                `font-size:24px;font-weight:700;margin-top:3px;color:${custody.unconfirmed === 0 ? "#2f6748" : "#a85f12"}`,
              )}
            >
              {custody.confirmed}/{custody.total}
            </div>
          </div>
          <div className="mono" style={css("font-size:11px;color:#5c6b71;line-height:1.6")}>
            {custody.unconfirmed} unconfirmed
            {active
              ? " · isolated authority — canonical state unchanged"
              : " · canonical authority"}
          </div>
        </div>
      ) : null}

      {evidence ? (
        <div
          data-testid="branch-evidence-result"
          data-decision={evidence.decision}
          style={css(
            `padding:12px 16px;border-top:1px solid #eceee9;background:${denied ? "#f9f0ee" : "#eef6f0"}`,
          )}
        >
          <div style={css("display:flex;align-items:center;gap:9px;flex-wrap:wrap")}>
            <span
              className="mono"
              data-testid="branch-decision"
              style={css(
                "font-size:9px;font-weight:700;letter-spacing:.07em;border-radius:5px;padding:4px 9px;" +
                  (denied
                    ? "color:#8a2f22;background:#f3ded9;border:1px solid #e3c3ba"
                    : "color:#2f6748;background:#d9ecdf;border:1px solid #a9cdb8"),
              )}
            >
              {denied ? "⦸ DENIED" : "✓ APPLIED IN ISOLATION"}
            </span>
            <span
              className="mono"
              data-testid="branch-mutations"
              data-domain-mutations={String(evidence.domainMutationsApplied)}
              data-evidence-mutations={String(evidence.evidenceMutationsApplied)}
              style={css(`font-size:10px;color:${denied ? "#8a2f22" : "#2f6748"};font-weight:600`)}
            >
              {evidence.domainMutationsApplied} domain · {evidence.evidenceMutationsApplied} evidence
              {evidence.domainMutationsApplied === 0 ? " — nothing in the domain changed" : ""}
            </span>
          </div>

          <div style={css(`font-size:12px;color:${denied ? "#8a2f22" : "#2f6748"};margin-top:8px;line-height:1.55`)}>
            {denied
              ? "The partner response asserted a confirmation it did not support. Custody stands unchanged and the acknowledgment obligation stays open."
              : `Every required claim carried a literal source anchor. Custody moved ${evidence.confirmedCasesBefore}→${evidence.confirmedCasesAfter} of ${evidence.totalCases}, inside this isolated authority only.`}
          </div>

          {evidence.reasons.length ? (
            <div style={css("display:flex;gap:6px;flex-wrap:wrap;margin-top:8px")}>
              {evidence.reasons.map((r) => (
                <span
                  key={r}
                  className="mono"
                  data-testid="branch-reason"
                  style={css(
                    "font-size:8.5px;font-weight:600;letter-spacing:.03em;color:#8a2f22;" +
                      "background:#f3ded9;border:1px solid #e3c3ba;border-radius:4px;padding:3px 7px",
                  )}
                >
                  {r.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          ) : null}

          {evidence.workItemId ? (
            <div className="mono" style={css("font-size:9.5px;color:#74848a;margin-top:8px;line-height:1.5")}>
              {evidence.workItemId} · {evidence.workItemBefore} → {evidence.workItemAfter}
              {evidence.receiptId ? ` · receipt ${evidence.receiptId}` : ""}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function BranchButton({
  testId,
  label,
  active,
  disabled,
  onClick,
}: {
  testId: string;
  label: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      style={css(
        `background:${active ? "#6f5da0" : disabled ? "#f1f3ef" : "#fff"};` +
          `color:${active ? "#fff" : disabled ? "#a8b2b6" : "#4c3f73"};` +
          `border:1px solid ${active ? "#6f5da0" : disabled ? "#e2e6df" : "#c3b7dd"};` +
          "border-radius:7px;padding:8px 15px;font-size:12px;font-weight:600;" +
          `cursor:${disabled ? "not-allowed" : "pointer"}`,
      )}
    >
      {label}
    </button>
  );
}
