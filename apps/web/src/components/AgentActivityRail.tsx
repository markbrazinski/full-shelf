import { css } from "../styles/css";
import { AGENT_ACCENT, AGENT_ST } from "../styles/tokens";
import type { AgentActivityView } from "../types/fullShelf";

interface Props {
  view: AgentActivityView;
  onOpenEvidence: () => void;
}

export function AgentActivityRail({ view, onOpenEvidence }: Props) {
  const notes: { glyph: string; fg: string; text: string }[] = [];
  for (const b of view.boundaries) notes.push({ glyph: "●", fg: "#3f7d5a", text: `${b.label} · ${b.detail}${b.pass ? " · PASS" : ""}` });
  if (view.governanceNote) notes.push({ glyph: "■", fg: "#a23b2b", text: view.governanceNote });

  // Find newest established (COMPLETED) agent for emphasis.
  const newest = [...view.agents]
    .reverse()
    .find((a) => a.status === "COMPLETED");
  const newestKey = newest?.key;

  return (
    <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:11px;padding:13px 16px;margin-bottom:18px")}>
      <div style={css("display:flex;align-items:center;justify-content:space-between;margin-bottom:11px")}>
        <div style={css("display:flex;align-items:center;gap:10px")}>
          <span className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600")}>AGENT ACTIVITY · {view.adkLabel}</span>
          <span style={css("font-size:11px;color:#93a1a6")}>{view.note}</span>
        </div>
        <span role="button" tabIndex={0} onClick={onOpenEvidence} onKeyDown={(e) => e.key === "Enter" && onOpenEvidence()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>Execution record →</span>
      </div>
      <div style={css("display:flex;align-items:stretch;gap:8px")}>
        {view.agents.map((a) => {
          const st = AGENT_ST[a.status];
          const accent = AGENT_ACCENT[a.key] || "#74848a";
          const resultFg = a.status === "COMPLETED" ? "#16323b" : "#93a1a6";
          const cellBg = a.key === newestKey ? "#f9f4f0" : a.isCoordinator ? "#f0f4f5" : "#fff";
          const cellBorder = a.key === newestKey ? "#e3c3ba" : a.isCoordinator ? "#cdd8da" : "#d5d8d2";
          const borderAccent = a.key === newestKey ? "#a23b2b" : accent;
          return (
            <div key={a.key} style={css(`flex:1;min-width:0;background:${cellBg};border:1px solid ${cellBorder};border-left:3px solid ${borderAccent};border-radius:8px;padding:9px 11px`)}>
              <div style={css("display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:5px")}>
                <span style={css("font-size:12px;font-weight:600;color:#16323b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis")}>{a.name}</span>
                <span className="mono" style={css(`font-size:10px;font-weight:700;letter-spacing:.03em;padding:2px 6px;border-radius:4px;background:${st.bg};color:${st.fg};white-space:nowrap;flex:none`)}>{st.label}</span>
              </div>
              <div style={css("font-size:11px;color:#5c6b71;line-height:1.35;min-height:15px")}>{a.task}</div>
              <div style={css(`font-size:11px;font-weight:600;color:${resultFg};line-height:1.35;margin-top:3px;min-height:15px`)}>{a.result ?? ""}</div>
              {a.isCoordinator && (
                <div className="mono" style={css("font-size:10px;letter-spacing:.04em;color:#93a1a6;margin-top:5px;padding-top:5px;border-top:1px solid #e3e8e9")}>COORDINATES · correlates specialist runs</div>
              )}
              {a.key === newestKey && a.status === "COMPLETED" && (
                <div className="mono" style={css("font-size:9px;letter-spacing:.08em;color:#a23b2b;margin-top:5px;padding-top:5px;border-top:1px solid #e3c3ba")}>NEWEST ESTABLISHED</div>
              )}
            </div>
          );
        })}
      </div>
      {notes.length > 0 && (
        <div style={css("display:flex;flex-wrap:wrap;gap:18px;margin-top:11px;padding-top:10px;border-top:1px solid #eceee9")}>
          {notes.map((n, i) => (
            <span key={i} style={css(`display:flex;align-items:center;gap:7px;font-size:11px;color:${n.fg}`)}>
              <span className="mono" style={css("font-weight:700")}>{n.glyph}</span>
              {n.text}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
