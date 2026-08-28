// =====================================================================
// Full Shelf — Fleet Activity rail
// ---------------------------------------------------------------------
// Append-only, NEWEST FIRST. One entry per COMMITTED event, driven
// entirely by the SSE envelope's own `activity_entry` (severity,
// headline, detail, action_required) and `effective_at`.
//
// The newest committed event is the most prominent card and sits at the
// top, so the current state never depends on scrolling to the bottom.
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

import { useEffect, useState } from "react";
import { css } from "../styles/css";

/** How many of the newest committed events the rail shows by default. */
const RECENT_LIMIT = 6;

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

export function FleetActivityRail({
  entries,
  onOpenReceipt,
}: {
  entries: ActivityRailEntry[];
  onOpenReceipt?: () => void;
}) {
  // Newest first. The runtime commits in ascending order, so the rail
  // renders the reverse of what it received; branch ordinals (`b1`…)
  // stay after canonical ones within the same isolated view.
  const ordered = [...entries].reverse();

  // Only a bounded recent set is shown, so the rail stays a supporting
  // column rather than an endless scroll. Everything older is one click
  // away and nothing is discarded.
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? ordered : ordered.slice(0, RECENT_LIMIT);
  const hidden = ordered.length - visible.length;

  // A newly committed event should bring the rail back to the top of the
  // recent set rather than leaving the operator deep in history.
  useEffect(() => {
    setShowAll(false);
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
          {entries.length} COMMITTED · NEWEST FIRST
        </span>
      </div>

      <div style={css("flex:1;min-height:0;overflow:auto;padding:9px 12px 14px")}>
        {entries.length === 0 ? (
          <div style={css("font-size:10.5px;color:#7e939c;line-height:1.5;padding:6px 2px")}>
            No committed events yet.
          </div>
        ) : null}

        {visible.map((e, index) => {
          const sev = SEV[e.severity] ?? SEV.INFO;
          const isolated = e.authority === "ISOLATED";
          const current = index === 0;
          return (
            <div
              key={`${e.authority}-${e.ordinal}`}
              // Entries are keyed by ordinal, so a newly committed event
              // mounts fresh and animates in; the ones below it are
              // reused and stay still. Only the arrival moves.
              className={`fs-stage-tween${current ? " fs-entry-enter" : ""}`}
              data-testid="activity-entry"
              data-ordinal={e.ordinal}
              data-severity={e.severity}
              data-authority={e.authority}
              data-current={String(current)}
              style={css(
                `background:${isolated ? "#1b2f38" : current ? "#1d414c" : "#173139"};` +
                  `border:1px solid ${isolated ? "#3c5361" : current ? "#356070" : "#22414a"};` +
                  `border-left:4px solid ${sev.accent};border-radius:9px;` +
                  `padding:${current ? "12px 13px" : "10px 12px"};margin-bottom:8px` +
                  (isolated ? ";border-style:dashed" : ""),
              )}
            >
              <div style={css("display:flex;align-items:center;gap:8px")}>
                <span className="mono" style={css(`font-size:12px;color:${sev.fg};flex:none;width:13px`)}>
                  {sev.glyph}
                </span>
                <span
                  style={css(
                    `font-size:${current ? "15px" : "13.5px"};font-weight:${current ? "700" : "600"};` +
                      "color:#f2f7f8;min-width:0;flex:1;line-height:1.3",
                  )}
                >
                  {e.headline}
                </span>
                <span className="mono" style={css("font-size:11px;color:#c3d5da;flex:none;font-weight:600")}>
                  {e.clock}
                </span>
              </div>

              {/* Only the current event carries its full detail. Older
                  entries stay one compact line so the newest result is
                  what the eye lands on. */}
              <div
                style={css(
                  `font-size:${current ? "14px" : "12px"};color:${current ? "#cfdee2" : "#a8bfc6"};` +
                    "margin-top:5px;line-height:1.45" +
                    (current
                      ? ""
                      : ";display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden"),
                )}
              >
                {e.detail}
              </div>

              <div
                style={css(
                  "display:flex;align-items:center;gap:7px;margin-top:" +
                    (current ? "7px" : "5px") +
                    ";flex-wrap:wrap",
                )}
              >
                <span
                  className="mono"
                  style={css(`font-size:9.5px;letter-spacing:.05em;color:${sev.fg};font-weight:700`)}
                >
                  {e.severity}
                </span>
                {e.actionRequired ? (
                  <span
                    className="mono"
                    data-testid="activity-action-required"
                    style={css(
                      "font-size:9.5px;letter-spacing:.05em;color:#f7d9a4;font-weight:700;" +
                        "background:#4a3a1c;border:1px solid #6d5527;border-radius:4px;padding:2px 6px",
                    )}
                  >
                    ACTION REQUIRED
                  </span>
                ) : null}
                {isolated ? (
                  <span
                    className="mono"
                    style={css(
                      "font-size:9.5px;letter-spacing:.05em;color:#d5c9ea;font-weight:700;" +
                        "background:#332b47;border:1px solid #574a75;border-radius:4px;padding:2px 6px",
                    )}
                  >
                    ISOLATED
                  </span>
                ) : null}
                <span className="mono" style={css("font-size:9.5px;color:#93a9b0;margin-left:auto")}>
                  #{e.ordinal}
                </span>
                {onOpenReceipt ? (
                  <button
                    type="button"
                    data-testid="activity-view-receipt"
                    onClick={onOpenReceipt}
                    className="mono"
                    style={css(
                      "font-size:9.5px;font-weight:700;letter-spacing:.04em;color:#9fd4ea;" +
                        "background:none;border:none;padding:0;cursor:pointer",
                    )}
                  >
                    View receipt →
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
        {hidden > 0 ? (
          <button
            type="button"
            data-testid="view-earlier-activity"
            onClick={() => setShowAll(true)}
            style={css(
              "width:100%;background:#173139;border:1px solid #2b4c56;color:#9fd4ea;border-radius:8px;" +
                "padding:8px 10px;font-size:12px;font-weight:600;cursor:pointer;margin-top:2px",
            )}
          >
            View earlier activity ({hidden})
          </button>
        ) : null}
      </div>
    </div>
  );
}
