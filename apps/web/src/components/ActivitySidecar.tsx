// =====================================================================
// Full Shelf — fleet activity sidecar (v6.1)
// ---------------------------------------------------------------------
// Reports ESTABLISHED evidence only. An agent appears here once the
// contract says it COMPLETED; there is no RUNNING state to render,
// because the contract cannot represent one truthfully.
//
// Model Armor is a safety boundary, not a sixth agent, and is rendered
// with a distinct square glyph so it can never read as fleet activity.
//
// Quiet is a real state. On an ordinary operating day with no reported
// activity the sidecar says so rather than inventing filler.
// =====================================================================

import { css } from "../styles/css";
import type { AgentActivityView, GovernanceView } from "../types/fullShelf";

const AGENT_ACCENT: Record<string, string> = {
  coord: "#4f97b0",
  recall: "#c79a5b",
  net: "#5aa07e",
  fulf: "#7f8fd0",
  part: "#c07f92",
};

export function ActivitySidecar({
  open,
  onToggle,
  activity,
  governance,
  onOpenExec,
}: {
  open: boolean;
  onToggle: () => void;
  activity?: AgentActivityView;
  governance?: GovernanceView;
  onOpenExec: () => void;
}) {
  // Only established reports. NOT_YET_REPORTED is absence, not activity.
  const established = (activity?.agents ?? []).filter((a) => a.status === "COMPLETED");
  const boundaries = activity?.boundaries ?? [];
  const hasEvents = established.length > 0 || boundaries.length > 0 || !!governance;

  return (
    <aside
      aria-label="Fleet activity"
      data-testid="activity-sidecar"
      style={css(
        `flex:none;width:${open ? "300px" : "50px"};background:#12292f;color:#a9bcc2;` +
          "border-left:1px solid #1e3a42;display:flex;flex-direction:column",
      )}
    >
      <div
        style={css(
          "flex:none;display:flex;align-items:center;gap:8px;padding:11px 12px;border-bottom:1px solid #1e3a42",
        )}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-label="Toggle activity sidecar"
          data-testid="sidecar-toggle"
          style={css(
            "background:#1f3d47;border:1px solid #2b4c56;color:#cfe0e4;border-radius:6px;" +
              "width:28px;height:28px;cursor:pointer;font-size:13px;flex:none",
          )}
        >
          {open ? "»" : "«"}
        </button>
        {open ? (
          <div style={css("min-width:0")}>
            <div style={css("font-size:12px;font-weight:600;color:#eef4f4")}>Fleet activity</div>
            <div className="mono" style={css("font-size:8.5px;color:#7e939c")} data-testid="sidecar-status">
              {hasEvents ? `${established.length} established` : "quiet · nominal"}
            </div>
          </div>
        ) : null}
      </div>

      {open ? (
        <div
          style={css(
            "flex:1;min-height:0;overflow:auto;padding:11px 12px;display:flex;flex-direction:column;gap:8px",
          )}
        >
          {!hasEvents ? (
            <div
              style={css("font-size:10.5px;color:#7e939c;line-height:1.5;padding:6px 2px")}
              data-testid="sidecar-quiet"
            >
              Quiet. The fleet reports established evidence here as incidents arise. No activity on an
              ordinary operating day.
            </div>
          ) : null}

          {/* Boundary first, and visually distinct: not an agent. */}
          {boundaries.map((b) => (
            <div
              key={b.label}
              data-testid="sidecar-boundary"
              style={css(
                "background:#173139;border:1px solid #1e3a42;border-left:3px solid #8ea1a7;border-radius:8px;padding:8px 10px",
              )}
            >
              <div style={css("display:flex;align-items:center;gap:7px")}>
                <span style={css("width:8px;height:8px;border-radius:2px;background:#8ea1a7;flex:none")} />
                <span style={css("font-size:10.5px;font-weight:600;color:#dce7e9;min-width:0")}>{b.label}</span>
                <span
                  className="mono"
                  style={css("font-size:7.5px;letter-spacing:.04em;color:#8ea1a7;margin-left:auto;flex:none")}
                >
                  BOUNDARY
                </span>
              </div>
              <div style={css("font-size:9.5px;color:#9fb4ba;margin-top:4px;line-height:1.4")}>
                {b.detail} · not an agent
              </div>
            </div>
          ))}

          {established.map((a) => (
            <div
              key={a.key}
              data-testid="sidecar-agent"
              style={css(
                "background:#173139;border:1px solid #1e3a42;border-left:3px solid " +
                  `${AGENT_ACCENT[a.key] ?? "#8ea1a7"};border-radius:8px;padding:8px 10px`,
              )}
            >
              <div style={css("display:flex;align-items:center;gap:7px")}>
                <span
                  style={css(
                    `width:8px;height:8px;border-radius:50%;background:${AGENT_ACCENT[a.key] ?? "#8ea1a7"};flex:none`,
                  )}
                />
                <span
                  style={css(
                    "font-size:10.5px;font-weight:600;color:#dce7e9;min-width:0;white-space:nowrap;" +
                      "overflow:hidden;text-overflow:ellipsis",
                  )}
                >
                  {a.name}
                </span>
                <span
                  className="mono"
                  style={css("font-size:7.5px;letter-spacing:.04em;color:#6fb39a;margin-left:auto;flex:none")}
                >
                  ESTABLISHED
                </span>
              </div>
              <div style={css("font-size:9.5px;color:#9fb4ba;margin-top:4px;line-height:1.4")}>
                {a.result ?? a.task}
              </div>
            </div>
          ))}

          {governance ? (
            <div
              data-testid="sidecar-refusal"
              style={css(
                "background:#173139;border:1px solid #1e3a42;border-left:3px solid #c14a34;border-radius:8px;padding:8px 10px",
              )}
            >
              <div style={css("display:flex;align-items:center;gap:7px")}>
                <span style={css("width:8px;height:8px;border-radius:2px;background:#c14a34;flex:none")} />
                <span style={css("font-size:10.5px;font-weight:600;color:#dce7e9")}>
                  Closure refused by deterministic policy
                </span>
              </div>
              <div className="mono" style={css("font-size:9.5px;color:#f0a99c;margin-top:4px;line-height:1.4")}>
                {governance.refusal.verdict}
              </div>
            </div>
          ) : null}

          {hasEvents ? (
            <button
              type="button"
              onClick={onOpenExec}
              style={css(
                "margin-top:2px;background:transparent;border:1px solid #2b4c56;color:#8fc6da;" +
                  "border-radius:7px;padding:7px;font-size:10px;font-weight:600;cursor:pointer",
              )}
            >
              Expand into Execution Record →
            </button>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
