// =====================================================================
// Full Shelf — service recovery: advisory (event 19) vs committed (20)
// ---------------------------------------------------------------------
// Two genuinely different states, never one panel with a changed word.
//
//   Event 19 — `current_day.recovery_proposal`, AMBER.
//     `mutation_applied: false`. Nothing has been allocated. The runtime
//     itself states the event at which it would commit. No committed
//     allocation exists in the projection yet.
//
//   Event 20 — `current_day.recovery`, GREEN.
//     Allocations are COMMITTED: 40 replacements (18 + 22) against safe
//     lot LTC-5090, with Agency 03 truthfully 20 short and OPEN.
//
// The shortfall is shown in BOTH states. A recovery that preserves most
// service is not a recovery that preserved all of it, and the gap stays
// visible rather than being filled with stock the evidence cannot support.
// =====================================================================

import { css } from "../styles/css";
import type { RecoveryProposalView, RecoveryView } from "../types/fullShelf";

/** Event 19. Advisory: proposed, not committed, zero mutations applied. */
export function RecoveryProposed({ proposal }: { proposal: RecoveryProposalView }) {
  return (
    <section
      data-testid="recovery-proposed"
      data-mutation-applied={String(proposal.mutationApplied)}
      style={css(
        "background:#fdf6e8;border:1px solid #e6cf9e;border-left:5px solid #c98a2e;" +
          "border-radius:11px;padding:15px 18px;display:flex;flex-direction:column;gap:12px",
      )}
    >
      <div style={css("display:flex;align-items:center;gap:10px;flex-wrap:wrap")}>
        <span
          className="mono"
          data-testid="recovery-status-badge"
          style={css(
            "font-size:9px;font-weight:700;letter-spacing:.07em;color:#8a5a12;" +
              "background:#f7e6c6;border:1px solid #e0bd83;border-radius:5px;padding:4px 9px",
          )}
        >
          ▲ PROPOSED · ADVISORY · NOT COMMITTED
        </span>
        <span className="mono" style={css("font-size:9px;color:#a07a2c;letter-spacing:.04em")}>
          AGENT PROPOSAL
        </span>
      </div>

      <div>
        <div className="mono" style={css("font-size:10px;letter-spacing:.12em;color:#a07a2c;font-weight:700")}>
          SERVICE RECOVERY · PROPOSED
        </div>
        <h1
          data-testid="recovery-proposed-headline"
          style={css("font-size:22px;font-weight:600;letter-spacing:-.015em;color:#16262c;margin-top:5px")}
        >
          {proposal.headline}
        </h1>
        <div
          data-testid="recovery-advisory-note"
          style={css("font-size:12.5px;color:#7a5c1c;margin-top:6px;line-height:1.55;max-width:640px")}
        >
          Nothing has been allocated. No domain mutation has been applied and no allocation
          exists in authoritative state
          {proposal.commitsAtEvent != null
            ? `; the runtime commits this proposal at event ${proposal.commitsAtEvent}.`
            : "."}
        </div>
      </div>

      <div style={css("display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:11px")}>
        <Figure
          testId="recovery-proposed-total"
          kicker="PROPOSED REPLACEMENTS"
          value={String(proposal.safeReplacements.total)}
          unit="cases"
          detail={proposal.safeReplacements.breakdown}
          accent="#a07a2c"
          bg="#f9edd6"
          border="#e6cf9e"
        />
        <Figure
          testId="recovery-proposed-shortfall"
          kicker="TRUTHFUL SHORTFALL"
          value={String(proposal.shortfall.value)}
          unit={`cases · ${proposal.shortfall.agency}`}
          detail={proposal.shortfall.note}
          accent="#a23b2b"
          bg="#f7e9e5"
          border="#e3c3ba"
        />
      </div>

      <div style={css("display:flex;flex-direction:column;gap:5px")}>
        {proposal.allocations.map((a) => (
          <div
            key={a.agencyId}
            data-testid="recovery-proposed-allocation"
            style={css(
              "display:flex;align-items:center;gap:10px;background:#fffaf0;border:1px dashed #e0bd83;" +
                "border-radius:8px;padding:8px 12px",
            )}
          >
            <span className="mono" style={css("font-size:11px;font-weight:700;color:#8a5a12;width:96px;flex:none")}>
              {a.agencyId}
            </span>
            <span style={css("font-size:12px;color:#16262c;flex:1")}>
              {a.cases} cases proposed
              {proposal.safeLotId ? ` from safe lot ${proposal.safeLotId}` : ""}
            </span>
            <span className="mono" style={css("font-size:9px;font-weight:700;color:#a07a2c;flex:none")}>
              {a.status}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Event 20. Committed: allocations applied, shortfall still truthfully open. */
export function RecoveryCommitted({ recovery }: { recovery: RecoveryView }) {
  return (
    <section
      data-testid="recovery-committed"
      style={css(
        "background:#eef6f0;border:1px solid #c4ddce;border-left:5px solid #3f7d5a;" +
          "border-radius:11px;padding:15px 18px;display:flex;flex-direction:column;gap:12px",
      )}
    >
      <div style={css("display:flex;align-items:center;gap:10px;flex-wrap:wrap")}>
        <span
          className="mono"
          data-testid="recovery-status-badge"
          style={css(
            "font-size:9px;font-weight:700;letter-spacing:.07em;color:#2f6748;" +
              "background:#d9ecdf;border:1px solid #a9cdb8;border-radius:5px;padding:4px 9px",
          )}
        >
          ✓ COMMITTED · ALLOCATED FROM SAFE STOCK
        </span>
        <span className="mono" style={css("font-size:9px;color:#3f7d5a;letter-spacing:.04em")}>
          COMMITTED LEDGER
        </span>
      </div>

      <div>
        <div className="mono" style={css("font-size:10px;letter-spacing:.12em;color:#3f7d5a;font-weight:700")}>
          SERVICE RECOVERY · COMMITTED
        </div>
        <h1
          data-testid="recovery-committed-headline"
          style={css("font-size:22px;font-weight:600;letter-spacing:-.015em;color:#16262c;margin-top:5px")}
        >
          {recovery.headline}
        </h1>
        <div style={css("font-size:12.5px;color:#3d5c4a;margin-top:6px;line-height:1.55;max-width:640px")}>
          {recovery.headlineDetail}
        </div>
      </div>

      <div style={css("display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:11px")}>
        <Figure
          testId="recovery-committed-total"
          kicker="SAFE REPLACEMENTS"
          value={String(recovery.safeReplacements.total)}
          unit="cases replaced"
          detail={recovery.safeReplacements.breakdown}
          accent="#2f6748"
          bg="#dfeee5"
          border="#a9cdb8"
        />
        <Figure
          testId="recovery-committed-shortfall"
          kicker="TRUTHFUL SHORTFALL"
          value={String(recovery.shortfall.value)}
          unit={`cases · ${recovery.shortfall.agency}`}
          detail={recovery.shortfall.note}
          accent="#a23b2b"
          bg="#f7e9e5"
          border="#e3c3ba"
        />
      </div>

      <div className="mono" style={css("font-size:10px;color:#5c6b71;line-height:1.55")}>
        {recovery.authorityNote}
      </div>
    </section>
  );
}

function Figure({
  testId,
  kicker,
  value,
  unit,
  detail,
  accent,
  bg,
  border,
}: {
  testId: string;
  kicker: string;
  value: string;
  unit: string;
  detail: string;
  accent: string;
  bg: string;
  border: string;
}) {
  return (
    <div data-testid={testId} style={css(`background:${bg};border:1px solid ${border};border-radius:9px;padding:12px 14px`)}>
      <div className="mono" style={css(`font-size:9px;letter-spacing:.1em;color:${accent};font-weight:700`)}>
        {kicker}
      </div>
      <div style={css("display:flex;align-items:baseline;gap:7px;margin-top:6px")}>
        <span className="mono" style={css(`font-size:26px;font-weight:700;color:${accent}`)}>{value}</span>
        <span style={css(`font-size:11.5px;color:${accent}`)}>{unit}</span>
      </div>
      <div style={css(`font-size:11px;color:${accent};margin-top:5px;line-height:1.5;opacity:.85`)}>{detail}</div>
    </div>
  );
}
