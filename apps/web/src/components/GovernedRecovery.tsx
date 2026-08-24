import { css } from "../styles/css";
import { AUTH_CLS, TONE, toneGlyph } from "../styles/tokens";
import type { RecoveryView } from "../types/fullShelf";

export function GovernedRecovery({ recovery, onOpenEvidence }: { recovery: RecoveryView; onOpenEvidence: () => void }) {
  return (
    <>
      <div style={css("margin-bottom:14px")}>
        <div className="mono" style={css("font-size:11px;letter-spacing:.12em;color:#74848a;font-weight:600")}>GOVERNED RECOVERY</div>
        {/* The benefit leads: what service was preserved, and what stays short. */}
        <h1
          style={css("font-size:24px;font-weight:600;letter-spacing:-.01em;margin-top:5px")}
          data-testid="recovery-headline"
        >
          {recovery.headline}
        </h1>
        <div style={css("font-size:13px;color:#5c6b71;margin-top:5px;line-height:1.5;max-width:640px")}>
          {recovery.headlineDetail}
        </div>
      </div>
      <div style={css("display:grid;grid-template-columns:1fr 340px;gap:18px;align-items:start")}>
        <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;overflow:hidden")}>
          <div style={css("display:grid;grid-template-columns:1fr 150px;column-gap:12px;padding:11px 16px;border-bottom:1px solid #eceee9;background:#faf9f5")}>
            <span className="mono" style={css("font-size:11px;letter-spacing:.06em;color:#74848a;font-weight:600")}>RECOVERY ITEM</span>
            <span className="mono" style={css("font-size:11px;letter-spacing:.06em;color:#74848a;font-weight:600")}>AUTHORITY CLASS</span>
          </div>
          {recovery.items.map((it, i) => {
            const cls = AUTH_CLS[it.authorityClass];
            return (
              <div key={i} style={css("display:grid;grid-template-columns:1fr 150px;column-gap:12px;padding:12px 16px;border-bottom:1px solid #f2f1ec;align-items:center")}>
                <div style={css("display:flex;gap:9px;align-items:flex-start")}>
                  <span className="mono" style={css(`font-size:12px;color:${TONE[it.tone].accent};margin-top:1px`)}>{toneGlyph(it.tone)}</span>
                  <span style={css("font-size:12px;color:#2b3b41;line-height:1.4")}>{it.text}</span>
                </div>
                <span className="mono" style={css(`font-size:10px;font-weight:600;letter-spacing:.03em;padding:3px 8px;border-radius:5px;justify-self:start;background:${cls.bg};color:${cls.fg};border:1px solid ${cls.border}`)}>{cls.label}</span>
              </div>
            );
          })}
          <div className="mono" style={css("font-size:11px;color:#74848a;padding:11px 16px;line-height:1.5;background:#faf9f5")}>{recovery.authorityNote}</div>
        </div>
        <div style={css("display:flex;flex-direction:column;gap:14px")}>
          <div style={css("background:#e5efe9;border:1px solid #c4ddce;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#3f7d5a;font-weight:600;margin-bottom:8px")}>SAFE REPLACEMENTS</div>
            <div style={css("display:flex;align-items:baseline;gap:8px")}>
              <span className="mono" style={css("font-size:28px;font-weight:600;color:#3f7d5a")}>{recovery.safeReplacements.total}</span>
              <span style={css("font-size:12px;color:#2f5f45")}>cases replaced safely</span>
            </div>
            <div style={css("font-size:12px;color:#2f5f45;margin-top:6px;line-height:1.5")}>{recovery.safeReplacements.breakdown}</div>
          </div>
          <div style={css("background:#f6ebd9;border:1px solid #e6cfa4;border-radius:10px;padding:15px 16px")}>
            <div className="mono" style={css("font-size:11px;letter-spacing:.1em;color:#a85f12;font-weight:600;margin-bottom:8px")}>TRUTHFUL SHORTFALL</div>
            <div style={css("display:flex;align-items:baseline;gap:8px")}>
              <span className="mono" style={css("font-size:28px;font-weight:600;color:#a85f12")}>{recovery.shortfall.value}</span>
              <span style={css("font-size:12px;color:#8a6a1f")}>cases · {recovery.shortfall.agency}</span>
            </div>
            <div style={css("font-size:12px;color:#8a6a1f;margin-top:6px;line-height:1.5")}>{recovery.shortfall.note}</div>
          </div>
          <div style={css("background:#fff;border:1px solid #d5d8d2;border-radius:10px;padding:14px 16px")}>
            <span role="button" tabIndex={0} onClick={onOpenEvidence} onKeyDown={(e) => e.key === "Enter" && onOpenEvidence()} style={css("font-size:12px;color:#1f6f8b;cursor:pointer;font-weight:600")}>Open execution record →</span>
          </div>
        </div>
      </div>
    </>
  );
}
