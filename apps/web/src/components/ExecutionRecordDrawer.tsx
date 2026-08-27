import { css } from "../styles/css";
import { AGENT_ST, specialistAccent } from "../styles/tokens";
import type { ExecutionEvidenceView } from "../types/fullShelf";

interface Props {
  evidence?: ExecutionEvidenceView;
  onClose: () => void;
}

export function ExecutionRecordDrawer({ evidence, onClose }: Props) {
  // Neutral placeholder when no coordinator execution exists for this beat.
  const ev: ExecutionEvidenceView =
    evidence ?? {
      title: "Execution record",
      context: "No coordinator execution recorded for this view.",
      coordinator: { name: "Incident Coordinator", status: "NOT_INVOLVED", result: null },
      correlationNote:
        "Specialist executions appear once an incident is active. Application-managed correlation, not native ADK parent-child lineage.",
      specialists: [],
      modelArmor: null,
      authority: {
        policyText:
          "Policy and the private ledger retain exclusive mutation authority. Agents propose; they do not mutate.",
        ledgerCommitted: false,
        ledgerReceiptRef: null,
        kmsKeyVersion: null,
        note: "",
      },
    };

  const coordSt = AGENT_ST[ev.coordinator.status];
  const ledgerLine = evidence
    ? ev.authority.ledgerReceiptRef ??
      (ev.authority.ledgerCommitted ? "Committed · reference bound in backend" : "Not committed")
    : "No commit for this view";
  const kmsLine = evidence
    ? (ev.authority.kmsKeyVersion ?? "Verification reference bound in backend")
    : "—";

  return (
    <div
      data-testid="execution-record-drawer"
      style={css("position:fixed;inset:0;z-index:60;display:flex;justify-content:flex-end")}
    >
      <div onClick={onClose} style={css("position:absolute;inset:0;background:rgba(16,32,37,.42)")} />
      <div className="fs-drawer" style={css("position:relative;width:468px;height:100%;background:#f4f2ec;box-shadow:-6px 0 24px rgba(16,32,37,.28);overflow-y:auto")}>
        <div style={css("position:sticky;top:0;z-index:2;background:#16323b;color:#f4f6f5;padding:16px 20px;display:flex;align-items:flex-start;justify-content:space-between")}>
          <div>
            <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#8fa6ac;font-weight:600")}>EXECUTION RECORD</div>
            <div style={css("font-size:16px;font-weight:600;margin-top:3px")}>{ev.title}</div>
            <div className="mono" style={css("font-size:11px;color:#a4b4ba;margin-top:3px")}>{ev.context}</div>
          </div>
          <span role="button" tabIndex={0} onClick={onClose} onKeyDown={(e) => e.key === "Enter" && onClose()} style={css("font-size:20px;color:#a4b4ba;cursor:pointer;line-height:1;padding:2px 6px")}>✕</span>
        </div>
        <div style={css("padding:18px 20px 26px")}>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:15px 16px;margin-bottom:14px")}>
            <div style={css("display:flex;align-items:center;justify-content:space-between;margin-bottom:10px")}>
              <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#74848a;font-weight:600")}>COORDINATOR EXECUTION</div>
              <span className="mono" style={css("font-size:10px;font-weight:600;padding:2px 7px;border-radius:4px;background:#e0eef1;color:#1f6f8b;border:1px solid #bcdae2")}>ADK 2.6.1</span>
            </div>
            <div style={css("display:flex;align-items:center;justify-content:space-between;gap:9px;margin-bottom:8px")}>
              <div style={css("display:flex;align-items:center;gap:9px")}>
                <span style={css("width:9px;height:9px;border-radius:50%;background:#4f9e73;flex:none")} />
                <div style={css("font-size:13px;font-weight:600")}>{ev.coordinator.name}</div>
              </div>
              <span className="mono" style={css(`font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;background:${coordSt.bg};color:${coordSt.fg}`)}>{coordSt.label}</span>
            </div>
            {ev.coordinator.result && <div style={css("font-size:12px;color:#16323b;font-weight:600;margin-bottom:9px")}>{ev.coordinator.result}</div>}
            <div className="mono" style={css("font-size:11px;color:#93a1a6;line-height:1.45")}>{ev.correlationNote}</div>
          </div>

          {ev.specialists.length > 0 && (
            <>
              <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#74848a;font-weight:600;margin-bottom:9px")}>SPECIALIST EXECUTIONS · CORRELATED</div>
              <div style={css("display:flex;flex-direction:column;gap:9px;margin-bottom:16px")}>
                {ev.specialists.map((s, i) => {
                  const st = AGENT_ST[s.status];
                  return (
                    <div key={i} style={css(`background:#fff;border:1px solid #d5d8d2;border-left:3px solid ${specialistAccent(s.name)};border-radius:9px;padding:12px 14px`)}>
                      <div style={css("display:flex;align-items:center;justify-content:space-between")}>
                        <span style={css("font-size:13px;font-weight:600")}>{s.name}</span>
                        <span className="mono" style={css(`font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;background:${st.bg};color:${st.fg}`)}>{st.label}</span>
                      </div>
                      <div style={css("font-size:12px;color:#43555c;margin-top:4px;line-height:1.4")}>{s.note}</div>
                      {s.toolUse && (
                        <div style={css("display:flex;align-items:center;gap:8px;margin-top:7px;flex-wrap:wrap")}>
                          <span className="mono" style={css("font-size:10px;color:#74848a")}>tool-use</span>
                          <span className="mono" style={css("font-size:11px;font-weight:600;background:#f0f4f5;border:1px solid #dfe4e0;border-radius:4px;padding:1px 6px")}>{s.toolUse.label}</span>
                          <span className="mono" style={css("font-size:11px;color:#93a1a6;flex:1;min-width:0")}>{s.toolUse.evidence}</span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {ev.modelArmor && (
            <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:14px 16px;margin-bottom:14px")}>
              <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#74848a;font-weight:600;margin-bottom:9px")}>SAFETY BOUNDARY · NOT AN AGENT</div>
              <div style={css("display:flex;align-items:center;justify-content:space-between")}>
                <div>
                  <div style={css("font-size:12px;font-weight:600")}>Model Armor · recall input screening</div>
                  <div style={css("font-size:11px;color:#43555c;margin-top:1px")}>Applied to the inbound recall notice before extraction.</div>
                </div>
                <span className="mono" style={css("font-size:11px;font-weight:600;color:#3f7d5a;flex:none")}>● PASS</span>
              </div>
            </div>
          )}

          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:15px 16px;margin-bottom:14px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#74848a;font-weight:600;margin-bottom:10px")}>AUTHORITY &amp; ACCOUNTING</div>
            <AuthRow glyph="⛭" glyphColor="#16323b" title="Deterministic policy result" body={ev.authority.policyText} />
            <AuthRow glyph="●" glyphColor="#3f7d5a" title="Ledger receipt" mono monoBody={ledgerLine} />
            <AuthRow glyph="●" glyphColor="#3f7d5a" title="KMS verification" mono monoBody={kmsLine} last />
          </div>

          {/* The ONE synthetic-replay disclosure. It lives here so the
              operating surfaces stay free of repeated demo disclaimers. */}
          <div
            data-testid="synthetic-replay-disclosure"
            style={css("background:#eef0ea;border:1px solid #dfe4e0;border-radius:10px;padding:12px 16px;margin-bottom:14px")}
          >
            <div className="mono" style={css("font-size:11px;letter-spacing:.08em;color:#74848a;font-weight:600;margin-bottom:6px")}>
              REPLAY DISCLOSURE
            </div>
            <div style={css("font-size:12px;color:#43555c;line-height:1.5")}>
              Synthetic replay using configured facilities and planned reference routes.
            </div>
          </div>

          {ev.refusal && (
            <div style={css("background:#2a1512;border:1px solid #5a2a20;border-radius:10px;padding:15px 16px")}>
              <div style={css("display:flex;align-items:center;gap:8px;margin-bottom:8px")}>
                <span className="mono" style={css("font-size:14px;color:#e88f7c")}>■</span>
                <span className="mono" style={css("font-size:12px;font-weight:700;letter-spacing:.06em;color:#f0b3a5")}>{ev.refusal.verdict}</span>
              </div>
              <div style={css("font-size:12px;color:#e6cec8;line-height:1.5")}>{ev.refusal.body}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AuthRow({ glyph, glyphColor, title, body, monoBody, mono, last }: { glyph: string; glyphColor: string; title: string; body?: string; monoBody?: string; mono?: boolean; last?: boolean }) {
  return (
    <div style={css(`display:flex;gap:9px;align-items:flex-start${last ? "" : ";margin-bottom:9px"}`)}>
      <span className="mono" style={css(`font-size:12px;color:${glyphColor};margin-top:1px`)}>{glyph}</span>
      <div>
        <div style={css("font-size:12px;font-weight:600")}>{title}</div>
        {body && <div style={css("font-size:12px;color:#43555c;margin-top:1px;line-height:1.4")}>{body}</div>}
        {monoBody && <div className={mono ? "mono" : undefined} style={css("font-size:11px;color:#93a1a6;margin-top:2px")}>{monoBody}</div>}
      </div>
    </div>
  );
}
