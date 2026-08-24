import { css } from "../styles/css";
import { POSTURE, TONE, toneGlyph } from "../styles/tokens";
import type { BeatId, CurrentDayView } from "../types/fullShelf";

interface Props {
  cd: CurrentDayView;
  onGo: (b: BeatId) => void;
}

export function DaybookHeader({ cd, onGo }: Props) {
  const posture = cd.posture ? POSTURE[cd.posture] : POSTURE.NORMAL;
  const authPill = cd.authPill;
  const authTone = authPill ? TONE[authPill.tone] : TONE.neutral;
  const oblig = cd.openObligations;
  const obligColor = oblig ? TONE[oblig.tone].accent : "#3f7d5a";
  const a = cd.needsAttention;
  const at = a ? TONE[a.tone] : TONE.neutral;

  return (
    <>
      <div style={css("display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:16px")}>
        <div>
          <div className="mono" style={css("font-size:11px;letter-spacing:.14em;color:#74848a;font-weight:600")}>OPERATING DAY</div>
          <div style={css("display:flex;align-items:center;gap:14px;margin-top:5px")}>
            <h1 style={css("font-size:29px;font-weight:600;letter-spacing:-.01em")}>{cd.dayLabel}</h1>
            <span className="mono" style={css(`font-size:12px;font-weight:600;padding:4px 9px;border-radius:5px;background:${posture.bg};color:${posture.fg};border:1px solid ${posture.border}`)}>{posture.glyph} {posture.label}</span>
          </div>
        </div>
        <div style={css("display:flex;gap:12px;align-items:stretch")}>
          <div style={css("display:flex;align-items:center;gap:14px;background:#fff;border:1px solid #d5d8d2;border-radius:9px;padding:11px 16px;min-width:300px")}>
            <div>
              <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600")}>AUTHORITATIVE PLAN REVISION</div>
              <div className="mono" style={css("font-size:19px;font-weight:600;color:#1a2a30;margin-top:2px")}>{cd.authRev}</div>
            </div>
            {authPill && (
              <span className="mono" style={css(`margin-left:auto;font-size:12px;font-weight:600;display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:6px;background:${authTone.bg};color:${authTone.fg};border:1px solid ${authTone.border}`)}>{authPill.glyph} {authPill.label}</span>
            )}
          </div>
          <div style={css("display:flex;flex-direction:column;justify-content:center;background:#fff;border:1px solid #d5d8d2;border-radius:9px;padding:10px 15px;min-width:132px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#74848a;font-weight:600")}>OPEN OBLIGATIONS</div>
            <div style={css("display:flex;align-items:baseline;gap:6px;margin-top:1px")}>
              <span className="mono" style={css(`font-size:19px;font-weight:600;color:${obligColor}`)}>{oblig?.count ?? 0}</span>
              <span style={css(`font-size:11px;color:${obligColor}`)}>{oblig?.note ?? ""}</span>
            </div>
          </div>
        </div>
      </div>

      {a && (
        <div style={css(`display:flex;align-items:center;gap:16px;background:${at.bg};border:1px solid ${at.border};border-left:5px solid ${at.accent};border-radius:11px;padding:15px 18px;margin-bottom:18px`)}>
          <span className="mono" style={css(`font-size:18px;color:${at.accent};flex:none`)}>{toneGlyph(a.tone)}</span>
          <div style={css("flex:1")}>
            <div className="mono" style={css(`font-size:11px;letter-spacing:.1em;font-weight:600;color:${at.accent}`)}>
              {a.kicker}<span style={css(`color:${at.fg};letter-spacing:.02em;font-weight:500`)}> {a.incident}</span>
            </div>
            <div style={css(`font-size:15px;font-weight:600;color:${at.fg};margin-top:3px`)}>{a.title}</div>
            <div style={css(`font-size:12px;color:${at.fg};margin-top:2px;line-height:1.4;opacity:.92`)}>{a.body}</div>
          </div>
          {a.action && (
            <button type="button" className="fs-brighten" onClick={() => onGo(a.action!.target)} style={css(`flex:none;background:${at.accent};color:#fff;border:none;border-radius:7px;padding:12px 18px;font-size:13px;font-weight:600;cursor:pointer;font-family:'IBM Plex Sans',sans-serif;white-space:nowrap;box-shadow:0 1px 0 rgba(22,50,59,.12)`)}>{a.action.label}</button>
          )}
        </div>
      )}
    </>
  );
}
