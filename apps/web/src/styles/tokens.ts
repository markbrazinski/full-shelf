// =====================================================================
// Presentation tokens — colors, glyphs, positions keyed by enum.
// This is styling ONLY (no scenario facts). Components import these to
// turn normalized enum values (tone, status, authority class) into the
// v4 look. Scenario text/numbers always come from the projection.
// =====================================================================

import type {
  AgentDisplayStatus,
  AuthorityClass,
  Connection,
  CustodyStatus,
  OrderStateTone,
  Posture,
  Tone,
} from "../types/fullShelf";

export interface ToneToken {
  bg: string;
  border: string;
  fg: string;
  accent: string;
}

export const TONE: Record<Tone, ToneToken> = {
  ok: { bg: "#e5efe9", border: "#c4ddce", fg: "#2f5f45", accent: "#3f7d5a" },
  info: { bg: "#e0eef1", border: "#bcdae2", fg: "#16536a", accent: "#1f6f8b" },
  warn: { bg: "#f6ebd9", border: "#e6cfa4", fg: "#8a6a1f", accent: "#a85f12" },
  crit: { bg: "#f3e5e1", border: "#e3c3ba", fg: "#8a2f22", accent: "#a23b2b" },
  neutral: { bg: "#eef1ee", border: "#d5d8d2", fg: "#5c6b71", accent: "#74848a" },
  plan: { bg: "#eef0ed", border: "#d5d8d2", fg: "#74848a", accent: "#74848a" },
};

export const toneGlyph = (t: Tone): string =>
  t === "ok" ? "●" : t === "warn" ? "▲" : t === "crit" ? "■" : t === "info" ? "◆" : "○";

export interface OrderToneToken {
  glyph: string;
  bg: string;
  fg: string;
  border: string;
}

export const ORDER_TONE: Record<OrderStateTone, OrderToneToken> = {
  delivered: { glyph: "●", bg: "#e5efe9", fg: "#3f7d5a", border: "#c4ddce" },
  planned: { glyph: "○", bg: "#eef0ed", fg: "#74848a", border: "#d5d8d2" },
  impacted: { glyph: "▲", bg: "#f6ebd9", fg: "#a85f12", border: "#e6cfa4" },
  reassigned: { glyph: "◆", bg: "#e0eef1", fg: "#1f6f8b", border: "#bcdae2" },
  partner: { glyph: "▲", bg: "#f6ebd9", fg: "#a85f12", border: "#e6cfa4" },
  recall: { glyph: "■", bg: "#f3e5e1", fg: "#a23b2b", border: "#e3c3ba" },
};

export interface AgentStatusToken {
  label: string;
  bg: string;
  fg: string;
}

export const AGENT_ST: Record<AgentDisplayStatus, AgentStatusToken> = {
  COMPLETED: { label: "COMPLETED", bg: "#e5efe9", fg: "#3f7d5a" },
  NOT_YET_REPORTED: { label: "NOT YET REPORTED", bg: "#e7ebe9", fg: "#5c6b71" },
  NOT_INVOLVED: { label: "NOT INVOLVED", bg: "#eef0ed", fg: "#8a938f" },
};

export const AGENT_ACCENT: Record<string, string> = {
  coord: "#16323b",
  recall: "#a23b2b",
  net: "#1f6f8b",
  fulf: "#3f7d5a",
  part: "#a85f12",
};

// Accent for a specialist row keyed by agent NAME (execution record).
export const specialistAccent = (name: string): string =>
  name.indexOf("Recall") >= 0
    ? "#a23b2b"
    : name.indexOf("Network") >= 0
      ? "#1f6f8b"
      : name.indexOf("Fulfillment") >= 0
        ? "#3f7d5a"
        : "#a85f12";

export interface AuthClsToken {
  label: string;
  bg: string;
  fg: string;
  border: string;
}

export const AUTH_CLS: Record<AuthorityClass, AuthClsToken> = {
  AGENT_PROPOSAL: { label: "AGENT PROPOSAL", bg: "#e0eef1", fg: "#1f6f8b", border: "#bcdae2" },
  DETERMINISTIC_POLICY: { label: "DET. POLICY", bg: "#eef1ee", fg: "#16323b", border: "#d5d8d2" },
  COMMITTED_LEDGER: { label: "COMMITTED", bg: "#e5efe9", fg: "#3f7d5a", border: "#c4ddce" },
  CONFIRMED: { label: "CONFIRMED", bg: "#e5efe9", fg: "#3f7d5a", border: "#c4ddce" },
  OPEN: { label: "OPEN", bg: "#f6ebd9", fg: "#a85f12", border: "#e6cfa4" },
};

export interface CustodyStatusToken {
  glyph: string;
  label: string;
  bg: string;
  fg: string;
  border: string;
  accent: string;
}

export const CUS_ST: Record<CustodyStatus, CustodyStatusToken> = {
  CONFIRMED: { glyph: "●", label: "CONFIRMED", bg: "#eef1ee", fg: "#5c6b71", border: "#d5d8d2", accent: "#93a1a6" },
  BLOCKED: { glyph: "■", label: "BLOCKED", bg: "#f3e5e1", fg: "#a23b2b", border: "#e3c3ba", accent: "#a23b2b" },
  UNCONFIRMED: { glyph: "▲", label: "UNCONFIRMED", bg: "#f6ebd9", fg: "#a85f12", border: "#e6cfa4", accent: "#a85f12" },
};

// Custody graph node positions (presentation geometry only).
export const CUS_POS: Record<string, { left: number; top: number; width?: number }> = {
  wh: { left: 212, top: 14 },
  t2: { left: 212, top: 82 },
  part: { left: 212, top: 150 },
  dr: { left: 212, top: 218 },
  a01: { left: 490, top: 286, width: 180 },
  s01: { left: 490, top: 372, width: 180 },
};

export interface ConnToken {
  label: string;
  dot: string;
  glow: string;
}

export const CONN: Record<Connection, ConnToken> = {
  CONNECTED: { label: "Live updates connected", dot: "#4f9e73", glow: "rgba(79,158,115,.25)" },
  MONITORING: { label: "Monitoring", dot: "#d69a3e", glow: "rgba(214,154,62,.25)" },
  DISCONNECTED: { label: "Disconnected", dot: "#a23b2b", glow: "rgba(162,59,43,.25)" },
};

export interface PostureToken {
  glyph: string;
  label: string;
  bg: string;
  fg: string;
  border: string;
}

export const POSTURE: Record<Posture, PostureToken> = {
  NORMAL: { glyph: "●", label: "NORMAL", bg: "#e5efe9", fg: "#3f7d5a", border: "#c4ddce" },
  INTERVENTION: { glyph: "▲", label: "INTERVENTION", bg: "#f6ebd9", fg: "#8a6a1f", border: "#e6cfa4" },
  RECALL: { glyph: "■", label: "RECALL", bg: "#f3e5e1", fg: "#a23b2b", border: "#e3c3ba" },
};

export interface IntakeToken {
  icon: string;
  dotBg: string;
  dotBorder: string;
  dotFg: string;
  lineBg: string;
  titleFg: string;
  tag: string;
  tagBg: string;
  tagFg: string;
  pulse: boolean;
}

export const INTAKE_ST: Record<"COMPLETE" | "IN_PROGRESS" | "PENDING", IntakeToken> = {
  COMPLETE: { icon: "✓", dotBg: "#e5efe9", dotBorder: "#3f7d5a", dotFg: "#2f5f45", lineBg: "#c4ddce", titleFg: "#16323b", tag: "COMPLETE", tagBg: "#e5efe9", tagFg: "#3f7d5a", pulse: false },
  IN_PROGRESS: { icon: "◴", dotBg: "#e0eef1", dotBorder: "#1f6f8b", dotFg: "#16536a", lineBg: "#eceee9", titleFg: "#16323b", tag: "IN PROGRESS", tagBg: "#e0eef1", tagFg: "#1f6f8b", pulse: true },
  PENDING: { icon: "○", dotBg: "#f4f2ec", dotBorder: "#cdd4cf", dotFg: "#93a1a6", lineBg: "#eceee9", titleFg: "#93a1a6", tag: "PENDING", tagBg: "#eef0ed", tagFg: "#8a938f", pulse: false },
};
