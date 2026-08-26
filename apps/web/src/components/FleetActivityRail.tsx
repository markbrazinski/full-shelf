// =====================================================================
// Full Shelf — Fleet Activity rail
// ---------------------------------------------------------------------
// Append-only and chronological. One entry per COMMITTED event, in the
// order the runtime committed it, driven entirely by the SSE envelope's
// own `activity_entry` (severity, headline, detail, action_required) and
// `effective_at`.
//
// This is not a static list of agent cards and carries no invented
// RUNNING / WAITING / duration / tool-call / ordering state — the runtime
// emits none, so none can be shown (contract §9 / D4). Agent evidence
// appears atomically at its committed boundary, which is exactly what one
// committed event is.
//
// Branch entries are visually separated and labelled ISOLATED so a proof
// event can never read as canonical history.
// =====================================================================

import { useEffect, useRef } from "react";
import { css } from "../styles/css";

export interface ActivityRailEntry {
  /** Canonical sequence integer, or a `b`-prefixed branch ordinal. */
  ordinal: string;
  clock: string;
  severity: string;
  headline: string;
  detail: string;
  actionRequired: boolean;
  authority: "CANONICAL" | "ISOLATED";
}

const SEV: Record<string, { accent: string; fg: string; glyph: string }> = {
  INFO: { accent: "#5e7982", fg: "#a9bcc2", glyph: "·" },
  SUCCESS: { accent: "#5aa07e", fg: "#9fd0b6", glyph: "✓" },
  ATTENTION: { accent: "#c98a2e", fg: "#f0c987", glyph: "▲" },
  CRITICAL: { accent: "#c14a34", fg: "#f0a99c", glyph: "■" },
  REFUSAL: { accent: "#c14a34", fg: "#f0a99c", glyph: "⦸" },
};

export function FleetActivityRail({ entries }: { entries: ActivityRailEntry[] }) {
  const endRef = useRef<HTMLDivElement | null>(null);

  // Append-only: the newest committed event stays in view.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [entries.length]);

  return (
    <div
      data-testid="fleet-activity-rail"
      style={css("flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden")}
    >
      <div
        style={css(
          "flex:none;display:flex;align-items:baseline;gap:8px;padding:11px 14px;border-bottom:1px solid #1e3a42",
        )}
      >
        <span style={css("font-size:12px;font-weight:600;color:#eef4f4")}>Fleet activity</span>
        <span
          className="mono"
          data-testid="activity-count"
          style={css("font-size:8.5px;color:#7e939c;letter-spacing:.06em;margin-left:auto")}
        >
          {entries.length} COMMITTED
        </span>
      </div>

      <div style={css("flex:1;min-height:0;overflow:auto;padding:9px 12px 14px")}>
        {entries.length === 0 ? (
          <div style={css("font-size:10.5px;color:#7e939c;line-height:1.5;padding:6px 2px")}>
            No committed events yet.
          </div>
        ) : null}

        {entries.map((e) => {
          const sev = SEV[e.severity] ?? SEV.INFO;
          const isolated = e.authority === "ISOLATED";
          return (
            <div
              key={`${e.authority}-${e.ordinal}`}
              data-testid="activity-entry"
              data-ordinal={e.ordinal}
              data-severity={e.severity}
              data-authority={e.authority}
              style={css(
                `background:${isolated ? "#1b2f38" : "#173139"};border:1px solid ${isolated ? "#3c5361" : "#1e3a42"};` +
                  `border-left:3px solid ${sev.accent};border-radius:8px;padding:8px 10px;margin-bottom:7px` +
                  (isolated ? ";border-style:dashed" : ""),
              )}
            >
              <div style={css("display:flex;align-items:center;gap:7px")}>
                <span className="mono" style={css(`font-size:10px;color:${sev.fg};flex:none;width:11px`)}>
                  {sev.glyph}
                </span>
                <span
                  style={css(
                    "font-size:10.5px;font-weight:600;color:#dce7e9;min-width:0;flex:1;" +
                      "white-space:nowrap;overflow:hidden;text-overflow:ellipsis",
                  )}
                >
                  {e.headline}
                </span>
                <span className="mono" style={css("font-size:8.5px;color:#7e939c;flex:none")}>
                  {e.clock}
                </span>
              </div>

              <div style={css("font-size:9.5px;color:#9fb4ba;margin-top:4px;line-height:1.45")}>
                {e.detail}
              </div>

              <div style={css("display:flex;align-items:center;gap:6px;margin-top:5px;flex-wrap:wrap")}>
                <span
                  className="mono"
                  style={css(
                    `font-size:7.5px;letter-spacing:.05em;color:${sev.fg};font-weight:700`,
                  )}
                >
                  {e.severity}
                </span>
                {e.actionRequired ? (
                  <span
                    className="mono"
                    data-testid="activity-action-required"
                    style={css(
                      "font-size:7.5px;letter-spacing:.05em;color:#f0c987;font-weight:700;" +
                        "background:#33291a;border:1px solid #5a4726;border-radius:4px;padding:1px 5px",
                    )}
                  >
                    ACTION REQUIRED
                  </span>
                ) : null}
                {isolated ? (
                  <span
                    className="mono"
                    style={css(
                      "font-size:7.5px;letter-spacing:.05em;color:#c9b8e0;font-weight:700;" +
                        "background:#2a2438;border:1px solid #4b3f66;border-radius:4px;padding:1px 5px",
                    )}
                  >
                    ISOLATED
                  </span>
                ) : null}
                <span className="mono" style={css("font-size:7.5px;color:#5e7982;margin-left:auto")}>
                  #{e.ordinal}
                </span>
              </div>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
    </div>
  );
}
