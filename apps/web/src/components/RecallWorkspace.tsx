import { css } from "../styles/css";
import { INTAKE_ST } from "../styles/tokens";
import type { BeatId, RecallView } from "../types/fullShelf";

interface Props {
  recall: RecallView;
  onToday: () => void;
  onGo: (b: BeatId) => void;
  onOpenEvidence: () => void;
}

export function RecallWorkspace({ recall, onToday, onGo, onOpenEvidence }: Props) {
  const armorPass = recall.modelArmor === "PASS";
  const affectedResolved = recall.affectedCommitments === "O202 · O203";
  return (
    <>
      <div style={css("display:flex;align-items:center;gap:10px;margin-bottom:12px")}>
        <span role="button" tabIndex={0} onClick={onToday} onKeyDown={(e) => e.key === "Enter" && onToday()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>← Today</span>
        <span className="mono" style={css("font-size:11px;color:#93a1a6")}>/</span>
        <span className="mono" style={css("font-size:12px;color:#74848a;letter-spacing:.02em")}>Recall {recall.ref} · Intake &amp; validation</span>
      </div>
      <div style={css("background:#f3e5e1;border:1px solid #e3c3ba;border-left:5px solid #a23b2b;border-radius:10px;padding:14px 18px;margin-bottom:16px;display:flex;align-items:center;gap:12px")}>
        <span className="mono" style={css("font-size:18px;color:#a23b2b")}>■</span>
        <div>
          <div style={css("font-size:15px;font-weight:600;color:#8a2f22")}>{recall.banner.title}</div>
          <div style={css("font-size:12px;color:#8a2f22;margin-top:2px")}>{recall.banner.body}</div>
        </div>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 380px;gap:18px;align-items:start")}>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:18px 20px")}>
          <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:16px")}>RECALL INTAKE PROGRESS</div>
          {recall.intake.map((step) => {
            const t = INTAKE_ST[step.status];
            return (
              <div key={step.key} style={css("display:flex;gap:14px;align-items:flex-start;position:relative")}>
                <div style={css("display:flex;flex-direction:column;align-items:center;flex:none")}>
                  <span className={t.pulse ? "fs-pulse" : undefined} style={css(`width:26px;height:26px;border-radius:50%;background:${t.dotBg};border:2px solid ${t.dotBorder};color:${t.dotFg};display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700`)}>{t.icon}</span>
                  <span style={css(`width:2px;flex:1;min-height:22px;background:${t.lineBg}`)} />
                </div>
                <div style={css("padding-bottom:16px;flex:1")}>
                  <div style={css("display:flex;align-items:center;gap:9px")}>
                    <span style={css(`font-size:13px;font-weight:600;color:${t.titleFg}`)}>{step.title}</span>
                    <span className="mono" style={css(`font-size:10px;font-weight:600;letter-spacing:.06em;padding:2px 7px;border-radius:4px;background:${t.tagBg};color:${t.tagFg}`)}>{t.tag}</span>
                  </div>
                  <div style={css("font-size:12px;color:#43555c;margin-top:3px;line-height:1.45")}>{step.body}</div>
                </div>
              </div>
            );
          })}
        </div>
        <div style={css("display:flex;flex-direction:column;gap:14px")}>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;overflow:hidden")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;padding:13px 16px;border-bottom:1px solid #eceee9")}>SOURCE NOTICE · EXCERPT</div>
            <div style={css("padding:14px 16px;background:#faf9f5;border-bottom:1px solid #eceee9")}>
              <div className="mono" style={css("font-size:12px;color:#2b3b41;line-height:1.6")}>{recall.sourceExcerpt}</div>
            </div>
            <div style={css("padding:12px 16px;display:flex;flex-direction:column;gap:9px")}>
              <div style={css("display:flex;justify-content:space-between;align-items:center")}>
                <span style={css("font-size:12px;color:#43555c")}>Model Armor · input screening</span>
                <span className="mono" style={css(`font-size:11px;font-weight:600;color:${armorPass ? "#3f7d5a" : "#a85f12"}`)}>{armorPass ? "● PASS" : "SCREENING…"}</span>
              </div>
              <div style={css("display:flex;justify-content:space-between;align-items:center")}>
                <span style={css("font-size:12px;color:#43555c")}>Source-anchored lot</span>
                <span className="mono" style={css("font-size:12px;font-weight:600;color:#a23b2b")}>{recall.sourceAnchoredLot}</span>
              </div>
              <div style={css("display:flex;justify-content:space-between;align-items:center")}>
                <span style={css("font-size:12px;color:#43555c")}>Affected commitments</span>
                <span className="mono" style={css(`font-size:12px;font-weight:600;color:${affectedResolved ? "#16323b" : "#93a1a6"}`)}>{recall.affectedCommitments}</span>
              </div>
            </div>
            <div style={css("padding:11px 16px;border-top:1px solid #eceee9")}>
              <span role="button" tabIndex={0} onClick={onOpenEvidence} onKeyDown={(e) => e.key === "Enter" && onOpenEvidence()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>Open execution record →</span>
            </div>
          </div>
          {recall.invalidation && (
            <div style={css("background:#16323b;border-radius:10px;padding:15px 16px;color:#f4f6f5")}>
              <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#f0c987;font-weight:600;margin-bottom:5px")}>■ {recall.invalidation.title}</div>
              <div style={css("font-size:12px;color:#c8d5d8;line-height:1.45")}>{recall.invalidation.body}</div>
              <span role="button" tabIndex={0} onClick={() => onGo("custodyEstablished")} onKeyDown={(e) => e.key === "Enter" && onGo("custodyEstablished")} style={css("display:inline-block;margin-top:11px;font-size:12px;color:#8fd0e4;cursor:pointer;font-weight:600")}>Open Custody impact →</span>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
