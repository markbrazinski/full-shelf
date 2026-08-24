import { css } from "../styles/css";
import { ORDER_TONE, TONE, toneGlyph } from "../styles/tokens";
import type { CurrentDayView } from "../types/fullShelf";

const COLS = "78px 92px 1fr 62px 128px 128px";

export function CommitmentsBoard({ cd, onHistory, onOpenEvidence }: { cd: CurrentDayView; onHistory: () => void; onOpenEvidence: () => void }) {
  const summary = cd.commitmentsSummary;
  const summaryFg = summary ? TONE[summary.tone].accent : "#74848a";
  return (
    <div style={css("display:grid;grid-template-columns:1fr 340px;gap:18px;align-items:start")}>
      <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;overflow:hidden")}>
        <div style={css("padding:13px 16px;border-bottom:1px solid #eceee9;display:flex;align-items:center;justify-content:space-between")}>
          <span style={css("font-size:14px;font-weight:600")}>Commitments</span>
          <span className="mono" style={css(`font-size:12px;color:${summaryFg};font-weight:600`)}>{summary?.label ?? ""}</span>
        </div>
        <div style={css(`display:grid;grid-template-columns:${COLS};column-gap:14px;padding:9px 16px;border-bottom:1px solid #eceee9;background:#faf9f5`)}>
          {["ORDER", "LOT", "DESTINATION", "CASES", "VEHICLE", "STATE"].map((h, i) => (
            <span key={h} className="mono" style={css(`font-size:11px;letter-spacing:.06em;color:#74848a;font-weight:600${i === 3 ? ";text-align:right" : ""}`)}>{h}</span>
          ))}
        </div>
        {(cd.commitments ?? []).map((c) => {
          const st = ORDER_TONE[c.stateTone];
          return (
            <div key={c.id} style={css(`display:grid;grid-template-columns:${COLS};column-gap:14px;padding:12px 16px;border-bottom:1px solid #f2f1ec;align-items:center`)}>
              <span className="mono" style={css("font-size:13px;font-weight:600")}>{c.id}</span>
              <span className="mono" style={css(`font-size:12px;color:${c.lotFlagged ? "#a23b2b" : "#43555c"}`)}>{c.lot}</span>
              <span style={css("font-size:13px")}>{c.agency}</span>
              <span className="mono" style={css("font-size:13px;text-align:right;font-weight:600")}>{c.cases}</span>
              <span style={css("font-size:12px;color:#43555c")}>{c.vehicle}</span>
              <span className="mono" style={css(`font-size:11px;font-weight:600;display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:5px;justify-self:start;background:${st.bg};color:${st.fg};border:1px solid ${st.border}`)}>{st.glyph} {c.stateLabel}</span>
            </div>
          );
        })}
      </div>

      <div style={css("display:flex;flex-direction:column;gap:14px")}>
        {cd.affectedPanel && (
          <div style={css("background:#f6ebd9;border:1px solid #e6cfa4;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css(`font-size:11px;letter-spacing:.1em;color:${TONE[cd.affectedPanel.tone].accent};font-weight:600;margin-bottom:9px`)}>{cd.affectedPanel.kicker}</div>
            <div style={css("display:flex;flex-direction:column;gap:7px")}>
              {cd.affectedPanel.lines.map((ln, i) => <div key={i} style={css("font-size:12px;color:#8a6a1f")}>{ln}</div>)}
            </div>
          </div>
        )}

        {cd.recallNoticePanel && (
          <div style={css("background:#f3e5e1;border:1px solid #e3c3ba;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#a23b2b;font-weight:600;margin-bottom:9px")}>{cd.recallNoticePanel.kicker}</div>
            <div style={css("display:flex;flex-direction:column;gap:6px")}>
              {cd.recallNoticePanel.lines.map((ln, i) => <div key={i} style={css("font-size:12px;color:#8a2f22;line-height:1.5")}>{ln}</div>)}
            </div>
          </div>
        )}

        {cd.capacity && (
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:11px")}>{cd.capacity.title}</div>
            <div style={css("height:18px;border-radius:5px;background:#e9ece9;overflow:hidden;display:flex;margin-bottom:7px")}>
              <div style={css(`width:${cd.capacity.fillPct}%;background:#93a1a6`)} />
            </div>
            <div className="mono" style={css("font-size:12px;color:#43555c")}>
              {cd.capacity.assignedLabel} · <span style={css("color:#3f7d5a;font-weight:600")}>{cd.capacity.spareLabel}</span> · {cd.capacity.note}
            </div>
          </div>
        )}

        {cd.approvalRecord && (
          <div style={css("background:#fff;border:1px solid #c4ddce;border-radius:10px;padding:16px;border-top:3px solid #3f7d5a")}>
            <div style={css("display:flex;align-items:center;justify-content:space-between;margin-bottom:11px")}>
              <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#3f7d5a;font-weight:600")}>● APPROVAL RECORD · {cd.authRev}</div>
              <span role="button" tabIndex={0} onClick={onOpenEvidence} onKeyDown={(e) => e.key === "Enter" && onOpenEvidence()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>Execution record →</span>
            </div>
            <div style={css("display:flex;flex-direction:column;gap:8px")}>
              <Row label="Decision" value={cd.approvalRecord.decision} />
              <Row label="Approver" value={`${cd.approvalRecord.approver} · ${cd.approvalRecord.role}`} />
              <Row label="Timestamp" value={cd.approvalRecord.timestamp} mono />
              <div style={css("border-top:1px dashed #d5d8d2;margin-top:4px;padding-top:9px")}>
                <div className="mono" style={css("font-size:11px;letter-spacing:.06em;color:#74848a")}>KMS VERIFICATION</div>
                <div className="mono" style={css("font-size:12px;color:#16323b;margin-top:2px;font-weight:600")}>{cd.approvalRecord.kmsKeyVersion}</div>
                <div className="mono" style={css("font-size:11px;color:#93a1a6;margin-top:2px")}>{cd.approvalRecord.kmsNote}</div>
              </div>
            </div>
          </div>
        )}

        {cd.obligationsNote && (
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600;margin-bottom:8px")}>OPEN OBLIGATIONS</div>
            <div style={css("font-size:13px;color:#74848a")}>{cd.obligationsNote}</div>
          </div>
        )}

        {cd.recentActivity && (
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:15px 16px")}>
            <div style={css("display:flex;align-items:center;justify-content:space-between;margin-bottom:10px")}>
              <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#74848a;font-weight:600")}>RECENT ACTIVITY</div>
              <span role="button" tabIndex={0} onClick={onHistory} onKeyDown={(e) => e.key === "Enter" && onHistory()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>View all →</span>
            </div>
            <div style={css("display:flex;flex-direction:column;gap:9px")}>
              {cd.recentActivity.map((r, i) => (
                <div key={i} style={css("display:flex;gap:9px;align-items:flex-start")}>
                  <span className="mono" style={css(`font-size:12px;color:${TONE[r.glyphTone].accent};margin-top:1px`)}>{toneGlyph(r.glyphTone)}</span>
                  <div>
                    <div style={css("font-size:12px;font-weight:600")}>{r.title}</div>
                    <div className="mono" style={css("font-size:11px;color:#74848a")}>{r.meta}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={css("display:flex;justify-content:space-between")}>
      <span style={css("font-size:12px;color:#43555c")}>{label}</span>
      <span className={mono ? "mono" : undefined} style={css("font-size:12px;font-weight:600")}>{value}</span>
    </div>
  );
}
