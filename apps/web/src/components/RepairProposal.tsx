// =====================================================================
// Full Shelf — refrigeration alarm and the repair proposal (v6.1)
// ---------------------------------------------------------------------
// The alarm is a reported mechanical fleet event with its own source and
// timestamp. It is NOT derived from position: refrigeration status and
// location are separate signals, and nothing here reads a coordinate.
//
// The proposal below is what the agents propose, never what anyone
// authorized. The active plan is unchanged until a verified human
// approves, and `Approve update` calls the real orchestrator endpoint
// that runs verified-human -> KMS -> ledger. There is no fake button and
// no freeform editor: the operator may approve exactly this diff, or
// leave it pending.
//
// Primary labels say "Active plan" and "Updated plan"; raw rev ids stay
// in the evidence line at the bottom.
// =====================================================================

import { useState } from "react";
import { css } from "../styles/css";
import type { RepairProposalView } from "../types/fullShelf";

export function RepairProposal({
  proposal,
  alarm,
  onApprove,
}: {
  proposal: RepairProposalView;
  alarm?: { vehicleId: string | null; receivedAt: string | null; source: string };
  onApprove: () => Promise<void>;
}) {
  const [state, setState] = useState<"pending" | "submitting" | "failed">("pending");
  const [error, setError] = useState<string | null>(null);

  const approve = async () => {
    setState("submitting");
    setError(null);
    try {
      await onApprove();
      // On success the projection reloads and the proposal disappears,
      // because the revision it repairs is no longer active.
    } catch (e: unknown) {
      setState("failed");
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const absorbing = proposal.absorbing;

  return (
    <div style={css("display:flex;flex-direction:column;gap:11px")} data-testid="repair-proposal">
      {/* ---------------------- refrigeration alarm ---------------------- */}
      {alarm ? (
        <div
          data-testid="refrigeration-alarm"
          style={css(
            "background:#fbf3e2;border:1px solid #e6cf9e;border-left:4px solid #c98a2e;" +
              "border-radius:10px;padding:11px 15px;display:flex;align-items:center;gap:12px;flex-wrap:wrap",
          )}
        >
          <div style={css("flex:1;min-width:220px")}>
            <div
              className="mono"
              style={css("font-size:10px;letter-spacing:.08em;color:#8a5a12;font-weight:700")}
            >
              {alarm.vehicleId ?? "VEHICLE"} REFRIGERATION ALARM
              {alarm.receivedAt ? ` · ${alarm.receivedAt}` : ""}
            </div>
            <div style={css("font-size:13px;font-weight:600;color:#16262c;margin-top:2px")}>
              Cold-chain capability unavailable · refrigerated commitments require recovery
            </div>
            <div className="mono" style={css("font-size:9px;color:#8a5a12;margin-top:4px")}>
              reported by {alarm.source}
            </div>
          </div>
        </div>
      ) : null}

      {/* ------------------------ repair proposal ------------------------ */}
      <div style={css("background:#fff;border:1px solid #dfe4e0;border-radius:12px;overflow:hidden")}>
        <div
          style={css(
            "padding:11px 16px;border-bottom:1px solid #eef0ea;background:#fafbf9;" +
              "display:flex;align-items:center;gap:10px;flex-wrap:wrap",
          )}
        >
          <span
            className="mono"
            style={css(
              "font-size:8.5px;font-weight:700;letter-spacing:.05em;color:#1f6f8b;" +
                "background:#e2edf1;border:1px solid #bcd6e0;border-radius:4px;padding:3px 7px",
            )}
            data-testid="proposal-authority"
          >
            {proposal.authority.replace(/_/g, " ")}
          </span>
          <span style={css("font-size:13px;font-weight:600;color:#16262c;flex:1")}>
            Proposed update to the active plan
          </span>
          <span
            className="mono"
            style={css(
              "font-size:9px;color:#8a5a12;background:#f7ecd6;border:1px solid #e6cf9e;" +
                "border-radius:5px;padding:3px 8px;font-weight:600",
            )}
          >
            AWAITING APPROVAL
          </span>
        </div>

        {/* Compact diff: exactly what will be committed, nothing more. */}
        <div style={css("padding:10px 16px;display:flex;flex-direction:column;gap:8px")}>
          <div
            style={css("display:flex;align-items:center;gap:10px")}
            data-testid="proposal-reroute"
          >
            <span
              className="mono"
              style={css("font-size:10px;font-weight:700;color:#1f6f8b;width:64px;flex:none")}
            >
              REROUTE
            </span>
            <span style={css("font-size:12px;color:#16262c;flex:1")}>
              {proposal.rerouteOrderId} · {proposal.rerouteCases} cases →{" "}
              {proposal.rerouteTargetVehicle}
            </span>
            {absorbing.projectedCases != null && absorbing.capacityCases != null ? (
              <span className="mono" style={css("font-size:11px;font-weight:700;color:#16262c")}>
                {absorbing.committedCases} + {proposal.rerouteCases} ={" "}
                {absorbing.projectedCases} / {absorbing.capacityCases}
              </span>
            ) : null}
          </div>
          <div
            style={css("display:flex;align-items:center;gap:10px")}
            data-testid="proposal-pickup"
          >
            <span
              className="mono"
              style={css("font-size:10px;font-weight:700;color:#a06a1c;width:64px;flex:none")}
            >
              PICKUP
            </span>
            <span style={css("font-size:12px;color:#16262c;flex:1")}>
              {proposal.pickupOrderId} · {proposal.pickupCases} cases → refrigerated partner pickup
            </span>
          </div>
        </div>

        <div
          style={css(
            "padding:11px 16px;border-top:1px solid #eef0ea;display:flex;align-items:center;gap:12px;flex-wrap:wrap",
          )}
        >
          <button
            type="button"
            onClick={approve}
            disabled={state === "submitting"}
            data-testid="approve-update"
            style={css(
              "background:#16323b;color:#eef4f4;border:none;border-radius:7px;padding:8px 16px;" +
                `font-size:12.5px;font-weight:600;cursor:${state === "submitting" ? "wait" : "pointer"}`,
            )}
          >
            {state === "submitting" ? "Submitting…" : "Approve update"}
          </button>
          <span style={css("font-size:11px;color:#5c6b71;flex:1;min-width:220px;line-height:1.5")}>
            The active plan stays authoritative until a verified human approves. Approval is
            KMS-bound to this exact change.
          </span>
        </div>

        {state === "failed" && error ? (
          <div
            data-testid="approval-error"
            style={css(
              "padding:10px 16px;border-top:1px solid #e6bcb0;background:#f5e1dc;" +
                "font-size:11px;color:#8a2f22;line-height:1.5",
            )}
          >
            Approval was not committed. Authoritative state did not change.
            <div className="mono" style={css("font-size:10px;color:#9a3322;margin-top:3px")}>
              {error}
            </div>
          </div>
        ) : null}

        {/* Raw identifiers live here, not in the primary hierarchy. */}
        <div
          className="mono"
          style={css(
            "padding:8px 16px;border-top:1px solid #f1f3ef;background:#fafbf9;" +
              "font-size:8.5px;color:#9aa6ab;line-height:1.6",
          )}
          data-testid="proposal-evidence"
        >
          <div>
            proposal · {proposal.proposalId} · {proposal.sourceRevision} →{" "}
            {proposal.proposedRevision}
          </div>
          {proposal.planDiffHash ? <div>plan diff hash · {proposal.planDiffHash}</div> : null}
          {proposal.sourceEventId ? <div>source event · {proposal.sourceEventId}</div> : null}
        </div>
      </div>
    </div>
  );
}
