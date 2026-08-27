// =====================================================================
// Full Shelf — custody network (the agent payoff)
// ---------------------------------------------------------------------
// Centered and unclipped: the whole 96 / 88 / 8 result is legible in one
// frame at 1600x900 without scrolling.
//
// Every node, quantity and custody state comes from the projection's own
// custody graph. The six current-position nodes sum to 96 exactly:
//
//     24 + 22 + 20 + 10 + 8 + 12 = 96
//
// O201's 18 cases are an INTERMEDIATE HISTORICAL SUBTOTAL and are never
// re-added, and Site 01's eight cases are downstream of Agency 01 and so
// are never double counted. The amber branch is the unconfirmed path.
// =====================================================================

import { css } from "../styles/css";
import type { CustodyView } from "../types/fullShelf";
import { facilityName } from "../data/contract/facilityNames";

/** Layout slots. Geometry is presentation; every value is projected. */
const SLOT: Record<string, { x: number; y: number; w: number }> = {
  "N-WH": { x: 336, y: 18, w: 250 },
  "N-TR2": { x: 336, y: 92, w: 250 },
  "N-STG": { x: 336, y: 166, w: 250 },
  "N-RESC": { x: 336, y: 240, w: 250 },
  "N-AG01": { x: 336, y: 314, w: 250 },
  "N-ST01": { x: 640, y: 314, w: 244 },
};

const SOURCE = { x: 40, y: 150, w: 210, h: 84 };

export function CustodyNetwork({
  custody,
  onOpenEvidence,
}: {
  custody: CustodyView;
  onOpenEvidence: () => void;
}) {
  const confirmedPct = custody.totalUnique
    ? (custody.confirmed / custody.totalUnique) * 100
    : 0;

  return (
    <div data-testid="custody-network" style={css("display:flex;flex-direction:column;gap:10px;min-width:0")}>
      {/* ---- the headline: 96 traced · 88 confirmed · 8 awaiting ----- */}
      <div style={css("display:flex;align-items:baseline;gap:13px;flex-wrap:wrap")}>
        <Figure value={custody.totalUnique} label="affected cases traced" color="#16262c" testId="custody-traced" />
        <Dot />
        <Figure value={custody.confirmed} label="confirmed" color="#1c5a3e" testId="custody-confirmed" />
        <Dot />
        <Figure
          value={custody.unconfirmed}
          label="awaiting confirmation"
          color="#8a5a12"
          testId="custody-unconfirmed"
        />
        <div
          style={css(
            "flex:1;min-width:110px;height:11px;background:#f0ead9;border-radius:6px;overflow:hidden;display:flex;margin-left:auto",
          )}
        >
          <span style={css(`width:${confirmedPct}%;background:#5aa07e`)} />
          <span style={css(`width:${100 - confirmedPct}%;background:#c98a2e`)} />
        </div>
      </div>

      <div
        className="mono"
        data-testid="custody-headline"
        style={css("font-size:11px;color:#4f5f65;letter-spacing:.01em;line-height:1.5")}
      >
        {custody.totalUnique} affected cases traced · {custody.confirmed} confirmed ·{" "}
        {custody.unconfirmed} awaiting confirmation
      </div>

      {/* ---- the network ------------------------------------------- */}
      <div
        style={css(
          "background:#f4f6f3;border:1px solid #e2e6df;border-radius:10px;padding:8px;min-width:0",
        )}
      >
        <svg
          viewBox="0 0 900 400"
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-labelledby="custody-net-title"
          style={css("display:block;width:100%;height:auto;max-height:340px")}
        >
          <title id="custody-net-title">
            Chain of custody for the recalled lot: {custody.totalUnique} cases traced from source
            across current positions; {custody.unconfirmed} cases at {facilityName("SITE-01")} are
            awaiting confirmation.
          </title>

          {/* edges from source to each current position */}
          {custody.nodes.map((n) => {
            const slot = SLOT[n.key];
            if (!slot || n.key === "N-ST01") return null;
            const y = slot.y + 26;
            return (
              <path
                key={`edge-${n.key}`}
                d={`M${SOURCE.x + SOURCE.w} ${SOURCE.y + SOURCE.h / 2} C ${SOURCE.x + SOURCE.w + 60} ${
                  SOURCE.y + SOURCE.h / 2
                }, ${slot.x - 60} ${y}, ${slot.x} ${y}`}
                stroke="#9fb0b5"
                strokeWidth="2"
                fill="none"
              />
            );
          })}

          {/* the sub-distribution edge: Agency 01 -> Site 01, unconfirmed */}
          {SLOT["N-AG01"] && SLOT["N-ST01"] ? (
            <path
              d={`M${SLOT["N-AG01"].x + SLOT["N-AG01"].w} ${SLOT["N-AG01"].y + 26} L ${SLOT["N-ST01"].x} ${
                SLOT["N-ST01"].y + 26
              }`}
              stroke="#c98a2e"
              strokeWidth="3.5"
              strokeDasharray="7 5"
              fill="none"
            />
          ) : null}

          {/* source lot */}
          <g>
            <rect
              x={SOURCE.x}
              y={SOURCE.y}
              width={SOURCE.w}
              height={SOURCE.h}
              rx="11"
              fill="#16323b"
              stroke="#4f97b0"
              strokeWidth="2"
            />
            <text
              x={SOURCE.x + SOURCE.w / 2}
              y={SOURCE.y + 26}
              textAnchor="middle"
              fill="#9fb4ba"
              fontSize="11"
              fontFamily="'IBM Plex Mono',monospace"
              letterSpacing="1"
            >
              LOT · SOURCE
            </text>
            <text
              x={SOURCE.x + SOURCE.w / 2}
              y={SOURCE.y + 48}
              textAnchor="middle"
              fill="#eef4f4"
              fontSize="16"
              fontWeight="700"
              fontFamily="'IBM Plex Mono',monospace"
            >
              LTC-4471
            </text>
            <text
              x={SOURCE.x + SOURCE.w / 2}
              y={SOURCE.y + 70}
              textAnchor="middle"
              fill="#8fc6da"
              fontSize="14"
              fontWeight="700"
              fontFamily="'IBM Plex Mono',monospace"
            >
              {custody.totalUnique} unique cases
            </text>
          </g>

          {/* current-position nodes */}
          {custody.nodes.map((n) => {
            const slot = SLOT[n.key];
            if (!slot) return null;
            const unconfirmed = n.status !== "CONFIRMED";
            return (
              <g key={n.key} data-testid={`custody-node-${n.key}`}>
                <rect
                  x={slot.x}
                  y={slot.y}
                  width={slot.w}
                  height="52"
                  rx="9"
                  fill={unconfirmed ? "#fbeecf" : "#ffffff"}
                  stroke={unconfirmed ? "#c98a2e" : "#cfd8d2"}
                  strokeWidth={unconfirmed ? "3" : "1.5"}
                />
                <text
                  x={slot.x + 14}
                  y={slot.y + 21}
                  fill="#16262c"
                  fontSize="12.5"
                  fontFamily="'IBM Plex Sans',sans-serif"
                  fontWeight="600"
                >
                  {facilityName(n.key) !== n.key ? facilityName(n.key) : n.label}
                </text>
                <text
                  x={slot.x + 14}
                  y={slot.y + 40}
                  fill={unconfirmed ? "#8a5a12" : "#41775c"}
                  fontSize="11.5"
                  fontFamily="'IBM Plex Mono',monospace"
                  fontWeight="700"
                >
                  {n.value} · {unconfirmed ? "AWAITING CONFIRMATION" : "confirmed"}
                </text>
                <text
                  x={slot.x + slot.w - 14}
                  y={slot.y + 32}
                  textAnchor="end"
                  fill={unconfirmed ? "#8a5a12" : "#16262c"}
                  fontSize="19"
                  fontFamily="'IBM Plex Mono',monospace"
                  fontWeight="700"
                >
                  {n.value}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* ---- the arithmetic, stated -------------------------------- */}
      <div style={css("display:flex;align-items:center;gap:12px;flex-wrap:wrap")}>
        <span
          className="mono"
          data-testid="custody-sum"
          style={css("font-size:11px;color:#4f5f65;line-height:1.5;flex:1;min-width:220px")}
        >
          {custody.sumExpression} unique · {custody.caveat}
        </span>
        <button
          type="button"
          onClick={onOpenEvidence}
          className="mono"
          style={css(
            "flex:none;background:#eef4f2;border:1px solid #cfe0d6;color:#1c5a3e;border-radius:6px;" +
              "padding:6px 10px;font-size:10px;font-weight:700;cursor:pointer",
          )}
        >
          OPEN CUSTODY RECEIPT →
        </button>
      </div>
    </div>
  );
}

function Figure({
  value,
  label,
  color,
  testId,
}: {
  value: number;
  label: string;
  color: string;
  testId: string;
}) {
  return (
    <span style={css("display:flex;align-items:baseline;gap:6px")}>
      <span
        className="mono"
        data-testid={testId}
        style={css(`font-size:30px;font-weight:700;color:${color};line-height:1`)}
      >
        {value}
      </span>
      <span style={css("font-size:11.5px;color:#4f5f65")}>{label}</span>
    </span>
  );
}

const Dot = () => <span style={css("color:#b9c2bc")}>·</span>;
