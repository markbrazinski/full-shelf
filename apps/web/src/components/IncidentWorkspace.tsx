// =====================================================================
// Full Shelf — one continuously unfolding Incident workspace
// ---------------------------------------------------------------------
// Replaces the Intake / Custody / Recovery / Selected-proof tabs with a
// single workspace that unfolds as canonical events commit.
//
// Everything here is derived from the projection and the committed
// cursor. A stage becomes reachable only once its establishing event has
// committed; a future stage reads "pending" and shows nothing. Reviewing
// a completed stage is NAVIGATION_ONLY — it pins what is displayed and
// never touches the runtime cursor.
//
// Agent presentation carries only what the runtime reports: upcoming,
// current responsibility, completed with receipt, or a recorded refusal.
// No RUNNING / WAITING / duration / confidence / reasoning state exists
// in the contract, so none can be shown.
// =====================================================================

import { useState } from "react";
import { css } from "../styles/css";
import type { FullShelfProjection } from "../types/fullShelf";
import { facilityName } from "../data/contract/facilityNames";
import { CustodyNetwork } from "./CustodyNetwork";
import { RecoveryProposed, RecoveryCommitted } from "./ServiceRecovery";
import { GovernanceRefusal } from "./GovernanceRefusal";

export type StageKey = "detect" | "scope" | "custody" | "recover" | "closure";

/**
 * The five stages, each bound to the canonical event that establishes it.
 * `minEvent` is the runtime's own sequence — never a UI guess.
 */
export const STAGES: {
  key: StageKey;
  num: string;
  label: string;
  minEvent: number;
  agent: string;
}[] = [
  { key: "detect", num: "1", label: "Detect & validate", minEvent: 11, agent: "Recall Extraction" },
  { key: "scope", num: "2", label: "Scope commitments", minEvent: 13, agent: "Incident Lead" },
  { key: "custody", num: "3", label: "Trace custody", minEvent: 18, agent: "Network & Custody" },
  { key: "recover", num: "4", label: "Recover service", minEvent: 19, agent: "Fulfillment & Recovery" },
  { key: "closure", num: "5", label: "Decide closure", minEvent: 21, agent: "Incident Lead" },
];

/** The five governed agents, in their fixed responsibility order. */
const AGENTS: { name: string; responsibility: string }[] = [
  { name: "Incident Lead", responsibility: "Coordinates the response and decides closure." },
  { name: "Recall Extraction", responsibility: "Extracts recall facts from the screened notice." },
  { name: "Network & Custody", responsibility: "Traces the chain of custody for the lot." },
  { name: "Fulfillment & Recovery", responsibility: "Sources safe replacement inventory." },
  { name: "Partner Operations", responsibility: "Arranges the refrigerated partner pickup." },
];

/** Presentation states an agent may legitimately be shown in. */
type AgentState = "upcoming" | "current" | "completed" | "refused";

const AGENT_STYLE: Record<AgentState, { bg: string; bd: string; bar: string; label: string; fg: string; chipBg: string }> = {
  upcoming: { bg: "#f7f8f6", bd: "#e2e6df", bar: "#b9c2bc", label: "UPCOMING", fg: "#5f6f74", chipBg: "#e8ebe6" },
  current: { bg: "#fbf3e2", bd: "#e6cf9e", bar: "#c98a2e", label: "CURRENT RESPONSIBILITY", fg: "#7a4f10", chipBg: "#f5e7cb" },
  completed: { bg: "#eef4f2", bd: "#cfe0d6", bar: "#2f7d5b", label: "COMPLETED · RECEIPT", fg: "#1c5a3e", chipBg: "#dff0e6" },
  refused: { bg: "#f5e1dc", bd: "#e6bcb0", bar: "#c14a34", label: "REFUSED BY POLICY", fg: "#8a2f22", chipBg: "#f7d9d2" },
};

/**
 * Which stage the runtime is actually working, from the committed cursor.
 * Returns -1 before the recall opens.
 */
export function currentStageIndex(cursor: number): number {
  let index = -1;
  STAGES.forEach((stage, i) => {
    if (stage.minEvent <= cursor) index = i;
  });
  return index;
}

/** Agent state at a cursor. Derived only from committed events. */
function agentStateAt(name: string, cursor: number, currentAgent: string | null): AgentState {
  // The Incident Lead proposed closure at 21 and deterministic policy
  // refused it. That refusal is a committed event, not an agent failure.
  if (name === "Incident Lead" && cursor >= 21) return "refused";

  const firstEvent: Record<string, number> = {
    "Incident Lead": 14,
    "Recall Extraction": 13,
    "Network & Custody": 18,
    "Fulfillment & Recovery": 19,
    "Partner Operations": 19,
  };
  const done = firstEvent[name];
  if (done === undefined || cursor < done) {
    return name === currentAgent ? "current" : "upcoming";
  }
  // Agent receipts commit atomically at event 20.
  if (cursor >= 20) return name === currentAgent ? "current" : "completed";
  return name === currentAgent ? "current" : "completed";
}

export function IncidentWorkspace({
  p,
  cursor,
  pinnedStage,
  onPinStage,
  onOpenEvidence,
  branchResolved = false,
}: {
  p: FullShelfProjection;
  cursor: number;
  pinnedStage: StageKey | null;
  onPinStage: (key: StageKey | null) => void;
  onOpenEvidence: () => void;
  /** Set only inside an isolated proof branch (debug-only). */
  branchResolved?: boolean;
}) {
  const recall = p.incidentSummary.incidents.find((i) => i.type === "FOOD_SAFETY_RECALL");
  const liveIndex = currentStageIndex(cursor);

  // A pinned stage only displays; it never moves the runtime. Pinning a
  // stage the incident has not reached is impossible by construction.
  const pinnedIndex = pinnedStage ? STAGES.findIndex((s) => s.key === pinnedStage) : -1;
  const viewIndex =
    pinnedIndex >= 0 && STAGES[pinnedIndex].minEvent <= cursor ? pinnedIndex : liveIndex;
  const viewStage = viewIndex >= 0 ? STAGES[viewIndex] : null;
  const currentAgent = liveIndex >= 0 ? STAGES[liveIndex].agent : null;

  const workItems = workToDo(cursor, p);

  return (
    <section
      data-testid="incident-workspace"
      data-current-stage={viewStage?.key ?? "none"}
      data-live-stage={liveIndex >= 0 ? STAGES[liveIndex].key : "none"}
      style={css("flex:none;display:flex;flex-direction:column;gap:11px;min-width:0")}
    >
      {/* ---- identity + authoritative lifecycle ---------------------- */}
      <div style={css("display:flex;align-items:center;gap:11px;flex-wrap:wrap")}>
        <span
          className="mono"
          style={css(
            "font-size:11px;font-weight:700;letter-spacing:.03em;color:#8a2f22;background:#f5e1dc;" +
              "border:1px solid #e6bcb0;border-radius:6px;padding:5px 10px;white-space:nowrap",
          )}
        >
          SAFETY HOLD · {recall?.affectedLotId ?? "—"}
        </span>
        <h1 style={css("font-size:19px;font-weight:600;color:#16262c;letter-spacing:-.01em")}>
          Recall {recall?.id ?? ""}
        </h1>
        {recall ? (
          <span
            className="mono"
            data-testid="incident-status"
            style={css(
              "font-size:10px;font-weight:700;letter-spacing:.06em;color:#7a4f10;background:#f8eedc;" +
                "border:1px solid #ead3a9;border-radius:5px;padding:5px 9px",
            )}
          >
            {recall.status}
          </span>
        ) : null}
      </div>

      {/* ---- five-stage progress spine ------------------------------- */}
      <div
        data-testid="stage-spine"
        style={css("display:flex;align-items:stretch;gap:7px;min-width:0")}
      >
        {STAGES.map((stage, i) => {
          const reached = stage.minEvent <= cursor;
          const state = i < liveIndex ? "done" : i === liveIndex ? "current" : "pending";
          const tone =
            state === "done"
              ? { bg: "#eef4f2", bd: "#cfe0d6", fg: "#1c5a3e", sub: "#41775c", numBg: "#bcd8c8", numFg: "#14472f" }
              : state === "current"
                ? { bg: "#fbf3e2", bd: "#e6cf9e", fg: "#7a4f10", sub: "#8a5a12", numBg: "#c98a2e", numFg: "#ffffff" }
                : { bg: "#f7f8f6", bd: "#e2e6df", fg: "#67757a", sub: "#7d8a8e", numBg: "#dfe4dd", numFg: "#67757a" };
          const focused = i === viewIndex;
          return (
            <button
              key={stage.key}
              type="button"
              data-testid={`stage-${stage.key}`}
              data-state={state}
              data-reached={String(reached)}
              aria-current={focused ? "step" : undefined}
              disabled={!reached}
              onClick={() => onPinStage(pinnedStage === stage.key ? null : stage.key)}
              title={reached ? "Review this stage" : "Opens as the incident reaches this stage"}
              style={css(
                `flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;background:${tone.bg};` +
                  `border:1px solid ${focused ? "#16323b" : tone.bd};border-radius:9px;padding:8px 10px;` +
                  `text-align:left;cursor:${reached ? "pointer" : "default"};` +
                  (focused ? "box-shadow:0 0 0 1px #16323b;" : ""),
              )}
            >
              <span style={css("display:flex;align-items:center;gap:7px;min-width:0")}>
                <span
                  className="mono"
                  style={css(
                    `font-size:9px;font-weight:700;width:17px;height:17px;line-height:17px;text-align:center;` +
                      `border-radius:50%;background:${tone.numBg};color:${tone.numFg};flex:none`,
                  )}
                >
                  {stage.num}
                </span>
                <span
                  style={css(
                    `font-size:11.5px;font-weight:700;color:${tone.fg};min-width:0;flex:1;` +
                      "white-space:nowrap;overflow:hidden;text-overflow:ellipsis",
                  )}
                >
                  {stage.label}
                </span>
              </span>
              <span
                className="mono"
                data-testid={`stage-${stage.key}-summary`}
                style={css(
                  `font-size:9px;letter-spacing:.02em;color:${tone.sub};` +
                    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis",
                )}
              >
                {state === "pending" ? "pending" : stageSummary(stage.key, cursor, p)}
              </span>
            </button>
          );
        })}
      </div>

      {/* ---- five-agent responsibility band -------------------------- */}
      <div
        data-testid="agent-band"
        style={css("display:flex;gap:8px;min-width:0")}
      >
        {AGENTS.map((agent) => {
          const state = agentStateAt(agent.name, cursor, currentAgent);
          const style = AGENT_STYLE[state];
          return (
            <div
              key={agent.name}
              data-testid={`agent-${agent.name.replace(/[^a-z]+/gi, "-").toLowerCase()}`}
              data-agent-state={state}
              style={css(
                `flex:1;min-width:0;background:${style.bg};border:1px solid ${style.bd};` +
                  `border-left:3px solid ${style.bar};border-radius:9px;padding:8px 10px`,
              )}
            >
              <div style={css("font-size:11px;font-weight:700;color:#16262c;line-height:1.2")}>
                {agent.name}
              </div>
              <div style={css("font-size:9.5px;color:#4f5f65;margin-top:4px;line-height:1.35;min-height:26px")}>
                {state === "refused"
                  ? "Proposed closure — deterministic policy refused it."
                  : agent.responsibility}
              </div>
              <div style={css("display:flex;align-items:center;gap:6px;margin-top:5px")}>
                <span
                  className="mono"
                  data-testid="agent-state-label"
                  style={css(
                    `font-size:7.5px;font-weight:700;letter-spacing:.04em;color:${style.fg};` +
                      `background:${style.chipBg};border-radius:4px;padding:2px 6px;white-space:nowrap`,
                  )}
                >
                  {style.label}
                </span>
                {state === "completed" || state === "refused" ? (
                  <button
                    type="button"
                    onClick={onOpenEvidence}
                    className="mono"
                    style={css(
                      "background:none;border:none;color:#1f6f8b;font-size:8px;font-weight:700;" +
                        "cursor:pointer;padding:0;margin-left:auto;white-space:nowrap",
                    )}
                  >
                    receipt →
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      {/* ---- dominant current work, then a compact Open work strip ---
          The primary stage result gets the full width and is rendered
          FIRST, so at events 21-22 the refusal headline, the blockers and
          the DENIED verdict all precede any obligations summary. Open
          work supports the takeaway; it never covers it. */}
      <div style={css("display:flex;flex-direction:column;gap:10px;min-width:0")}>
        <div
          data-testid="dominant-section"
          data-stage={viewStage?.key ?? "none"}
          style={css(
            "min-width:0;background:#fff;border:1px solid #dfe4e0;border-radius:11px;overflow:hidden",
          )}
        >
          <div
            style={css(
              "display:flex;align-items:center;gap:9px;padding:10px 15px;border-bottom:1px solid #eef0ea;background:#fafbf9",
            )}
          >
            <span
              className="mono"
              data-testid="dominant-heading"
              style={css("font-size:10px;letter-spacing:.06em;font-weight:700;color:#3f5157")}
            >
              {viewStage ? `${viewStage.agent.toUpperCase()} · ${viewStage.label.toUpperCase()}` : "NO ACTIVE STAGE"}
            </span>
            {viewIndex !== liveIndex && viewIndex >= 0 ? (
              <button
                type="button"
                data-testid="stage-unpin"
                onClick={() => onPinStage(null)}
                className="mono"
                style={css(
                  "margin-left:auto;font-size:8.5px;font-weight:700;letter-spacing:.04em;color:#1f6f8b;" +
                    "background:#e6eff3;border:1px solid #bcd6e0;border-radius:5px;padding:3px 8px;cursor:pointer",
                )}
              >
                REVIEWING · BACK TO CURRENT
              </button>
            ) : (
              <span
                className="mono"
                style={css("margin-left:auto;font-size:8.5px;color:#6d7f84")}
              >
                STAGE {viewIndex >= 0 ? viewIndex + 1 : "—"} / 5
              </span>
            )}
          </div>

          <div style={css("padding:12px 15px;min-width:0;max-height:496px;overflow:auto")}>
            {viewStage?.key === "detect" ? <DetectStage p={p} onOpenEvidence={onOpenEvidence} /> : null}
            {viewStage?.key === "scope" ? <ScopeStage p={p} cursor={cursor} /> : null}
            {viewStage?.key === "custody" ? (
              p.custody ? (
                <CustodyNetwork custody={p.custody} onOpenEvidence={onOpenEvidence} />
              ) : (
                <Pending text="Custody reconciliation has not been committed at this boundary." />
              )
            ) : null}
            {viewStage?.key === "recover" ? (
              p.recovery ? (
                <RecoveryCommitted recovery={p.recovery} />
              ) : p.recoveryProposal ? (
                <RecoveryProposed proposal={p.recoveryProposal} />
              ) : (
                <Pending text="No recovery has been proposed at this boundary." />
              )
            ) : null}
            {viewStage?.key === "closure" ? (
              // Inside an isolated proof where the outstanding cases DID
              // resolve, the canonical refusal headline would contradict
              // the branch's own result, so the branch outcome is shown
              // instead. Canonical state is untouched and restored on exit.
              branchResolved ? (
                <BranchResolvedClosure />
              ) : p.governance ? (
                <GovernanceRefusal governance={p.governance} onOpenEvidence={onOpenEvidence} />
              ) : (
                <Pending text="No closure decision has been committed at this boundary." />
              )
            ) : null}
            {!viewStage ? (
              <Pending text="The recall has not been received at this boundary." />
            ) : null}
          </div>
        </div>

        {/* ---- compact Open work summary ---------------------------- */}
        <OpenWork items={workItems} />
      </div>
    </section>
  );
}

/**
 * Bounded obligations summary.
 *
 * One line per obligation, collapsed by default and capped in height, so
 * it can never compete with — or overlay — the stage conclusion above it.
 */
function OpenWork({ items }: { items: ReturnType<typeof workToDo> }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;

  return (
    <div
      data-testid="work-to-do"
      data-open-count={String(items.length)}
      style={css(
        "min-width:0;background:#16323b;border-radius:10px;color:#dce7e9;" +
          `padding:8px 12px;max-height:${open ? "240px" : "112px"};overflow:auto`,
      )}
    >
      <button
        type="button"
        data-testid="work-to-do-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={css(
          "width:100%;display:flex;align-items:center;gap:8px;background:none;border:none;" +
            "padding:0;cursor:pointer;color:inherit;text-align:left",
        )}
      >
        <span
          className="mono"
          data-testid="work-to-do-count"
          style={css("font-size:10px;letter-spacing:.06em;color:#9fb4ba;font-weight:700")}
        >
          OPEN WORK · {items.length}
        </span>
        <span className="mono" style={css("font-size:9px;color:#9fd4ea;margin-left:auto")}>
          {open ? "Hide details" : "Show details"}
        </span>
      </button>

      <div style={css("display:flex;flex-direction:column;gap:3px;margin-top:6px")}>
        {items.map((item) => (
          <div
            key={item.title}
            data-testid="work-item"
            style={css("display:flex;align-items:baseline;gap:8px;min-width:0")}
          >
            <span
              className="mono"
              style={css(
                `font-size:7.5px;font-weight:700;letter-spacing:.04em;color:${item.tagFg};` +
                  `background:${item.tagBg};border-radius:4px;padding:2px 6px;flex:none`,
              )}
            >
              {item.tag}
            </span>
            <div style={css("min-width:0;flex:1")}>
              <div
                style={css(
                  "font-size:11px;color:#eef4f4;line-height:1.3;" +
                    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis",
                )}
              >
                {item.title}
              </div>
              {open ? (
                <div style={css("font-size:10px;color:#a9c0c6;margin-top:2px;line-height:1.4")}>
                  {item.body}
                </div>
              ) : null}
            </div>
            <span
              className="mono"
              style={css(`font-size:7.5px;font-weight:700;color:${item.tagFg};flex:none`)}
            >
              {item.state}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------

/** One-line collapsed summary for a reached stage. Projection-derived. */
function stageSummary(key: StageKey, cursor: number, p: FullShelfProjection): string {
  switch (key) {
    case "detect":
      return p.recall?.modelArmor === "PASS" ? "screened · PASS" : "screening notice";
    case "scope":
      return cursor >= 15 ? "O202 · O203 · barrier" : "scoping commitments";
    case "custody":
      return p.custody
        ? `${p.custody.totalUnique} · ${p.custody.confirmed} · ${p.custody.unconfirmed}`
        : "tracing custody";
    case "recover":
      return p.recovery
        ? `${p.recovery.safeReplacements.total} replaced · ${p.recovery.shortfall.value} short`
        : "sourcing replacements";
    case "closure":
      return cursor >= 22 ? "partially contained" : "closure refused";
  }
}

/** The standing obligations, opened by their own committed events. */
function workToDo(cursor: number, p: FullShelfProjection) {
  const items: {
    tag: string;
    tagFg: string;
    tagBg: string;
    bar: string;
    state: string;
    title: string;
    body: string;
  }[] = [];

  if (cursor >= 15) {
    items.push({
      tag: "CUSTODY",
      tagFg: "#f0c987",
      tagBg: "#3a3320",
      bar: "#c98a2e",
      state: "OPEN",
      title: `Confirm ${p.custody?.unconfirmed ?? 8} cases at ${facilityName("SITE-01")}`,
      body:
        cursor >= 18
          ? "Forwarded from Berkeley Community Pantry and still unconfirmed."
          : "Acknowledgment work item opened; the count confirms at custody.",
    });
  }
  if (cursor >= 20) {
    items.push({
      tag: "RECOVERY",
      tagFg: "#f0c987",
      tagBg: "#3a3320",
      bar: "#c98a2e",
      state: "OPEN",
      title: `Fulfill the ${p.recovery?.shortfall.value ?? 20}-case ${facilityName("AGENCY-03")} shortfall`,
      body: "No confirmed-safe lot yet · carried to Saturday demand first.",
    });
  }
  if (cursor >= 15) {
    items.push({
      tag: "SAFETY",
      tagFg: "#f0a99c",
      tagBg: "#3a2320",
      bar: "#c14a34",
      state: "ACTIVE",
      title: "Maintain the LTC-4471 movement barrier",
      body: "The barrier stays active until disposition.",
    });
    items.push({
      tag: "INCIDENT",
      tagFg: "#a9bcc2",
      tagBg: "#24454f",
      bar: "#8ea1a7",
      state: cursor >= 21 ? "BLOCKED" : "OPEN",
      title: "Resolve the incident before closure",
      body:
        cursor >= 21
          ? "Closure refused while confirmation work remains."
          : "Open until custody and recovery obligations clear.",
    });
  }
  return items;
}

/**
 * Closure as it reads inside a proof branch whose evidence resolved the
 * outstanding cases. Clearly labelled isolated: it is what WOULD follow,
 * never a canonical outcome.
 */
function BranchResolvedClosure() {
  return (
    <div
      data-testid="branch-resolved-closure"
      style={css(
        "background:#f7f5fb;border:1px solid #c3b7dd;border-left:4px solid #6f5da0;" +
          "border-radius:11px;padding:14px 16px",
      )}
    >
      <div
        className="mono"
        style={css("font-size:9.5px;letter-spacing:.07em;font-weight:700;color:#4c3f73")}
      >
        ISOLATED PROOF · CLOSURE BLOCKERS CLEARED
      </div>
      <div style={css("font-size:15px;font-weight:700;color:#16262c;margin-top:7px;line-height:1.3")}>
        All affected cases confirmed in this isolated proof
      </div>
      <div style={css("font-size:11.5px;color:#3a4a50;margin-top:7px;line-height:1.5")}>
        With a sufficient partner response applied, custody reaches 96 / 96 and the confirmation
        blocker clears. This is an isolated evaluation: canonical custody remains 88 / 96 and the
        incident stays PARTIALLY_CONTAINED until real evidence arrives.
      </div>
    </div>
  );
}

function Pending({ text }: { text: string }) {
  return (
    <div
      data-testid="stage-pending"
      style={css(
        "border:1px dashed #d5d8d2;border-radius:9px;padding:22px;text-align:center;" +
          "font-size:12.5px;color:#5f6f74;line-height:1.6",
      )}
    >
      {text}
    </div>
  );
}

// ---------------------------- stage bodies ---------------------------

function DetectStage({ p, onOpenEvidence }: { p: FullShelfProjection; onOpenEvidence: () => void }) {
  const recall = p.recall;
  if (!recall) return <Pending text="No recall intake has been committed at this boundary." />;
  const screened = recall.modelArmor === "PASS";

  return (
    <div style={css("display:flex;flex-direction:column;gap:11px")}>
      <div
        style={css("background:#f5e1dc;border:1px solid #e6bcb0;border-radius:10px;padding:12px 14px")}
      >
        <div
          className="mono"
          style={css("font-size:9px;letter-spacing:.07em;color:#8a2f22;font-weight:700")}
        >
          RECALL NOTICE · {p.recallSource?.channel.replace(/_/g, " ") ?? "REGULATORY FEED"} · UNTRUSTED SOURCE
        </div>
        <div style={css("font-size:12.5px;color:#3a4a50;margin-top:8px;line-height:1.5")}>
          Affected lot{" "}
          <span className="mono" style={css("font-weight:700;color:#8a2f22")}>
            {recall.sourceAnchoredLot}
          </span>{" "}
          · {recall.affectedCommitments}
        </div>
      </div>

      <div style={css("background:#fafbf9;border:1px solid #eef0ea;border-radius:10px;padding:12px 14px")}>
        <div
          className="mono"
          style={css("font-size:9px;letter-spacing:.07em;color:#5f6f74;font-weight:700")}
        >
          VALIDATION PIPELINE
        </div>
        <div style={css("display:flex;align-items:center;gap:9px;margin-top:10px;flex-wrap:wrap")}>
          <span
            style={css(
              "font-size:11px;color:#8a2f22;background:#f5e1dc;border-radius:6px;padding:6px 10px;font-weight:600",
            )}
          >
            Untrusted notice
          </span>
          <span style={css("color:#7d8a8e")}>→</span>
          <span
            data-testid="model-armor-state"
            style={css(
              `font-size:11px;font-weight:600;border-radius:6px;padding:6px 10px;` +
                (screened
                  ? "color:#1c5a3e;background:#e3f0e8;border:1px solid #bcd8c8"
                  : "color:#7a4f10;background:#f7ecd6;border:1px solid #e6cf9e"),
            )}
          >
            {screened ? "Model Armor · PASS" : "Screening…"}
          </span>
          <span style={css("color:#7d8a8e")}>→</span>
          <span
            style={css(
              `font-size:11px;font-weight:600;border-radius:6px;padding:6px 10px;` +
                (screened
                  ? "color:#16536a;background:#e2edf1"
                  : "color:#7a4f10;background:#f7ecd6"),
            )}
          >
            {screened ? "Extraction permitted" : "Pending screening"}
          </span>
        </div>
        <div style={css("font-size:11px;color:#4f5f65;margin-top:10px;line-height:1.5")}>
          Model Armor screens the inbound notice before any agent reads it — a safety boundary,{" "}
          <strong>not</strong> one of the five agents.
        </div>
        <button
          type="button"
          onClick={onOpenEvidence}
          style={css(
            "margin-top:10px;background:none;border:none;padding:0;font-size:11.5px;" +
              "color:#1f6f8b;font-weight:600;cursor:pointer",
          )}
        >
          Open execution record →
        </button>
      </div>
    </div>
  );
}

function ScopeStage({ p, cursor }: { p: FullShelfProjection; cursor: number }) {
  const barrier = cursor >= 15;
  const invalidated = cursor >= 17;
  const commitments = p.currentDay.commitments ?? [];
  const affected = commitments.filter((c) => c.lotFlagged);

  return (
    <div style={css("display:flex;flex-direction:column;gap:11px")}>
      <div style={css("display:flex;gap:10px;flex-wrap:wrap")}>
        <div
          data-testid="movement-barrier"
          style={css(
            `flex:1;min-width:190px;border-radius:9px;padding:10px 12px;` +
              (barrier
                ? "background:#f5e1dc;border:1px solid #e6bcb0"
                : "background:#fbf3e2;border:1px solid #e6cf9e"),
          )}
        >
          <div
            className="mono"
            style={css(
              `font-size:9px;letter-spacing:.06em;font-weight:700;color:${barrier ? "#8a2f22" : "#7a4f10"}`,
            )}
          >
            {barrier ? "MOVEMENT BARRIER · ACTIVE" : "MOVEMENT BARRIER · PENDING"}
          </div>
          <div style={css("font-size:12px;font-weight:600;color:#16262c;margin-top:5px;line-height:1.35")}>
            {barrier
              ? "Lot-level barrier on LTC-4471 — affected movement held."
              : "The barrier commits as containment begins."}
          </div>
        </div>
        <div
          style={css(
            `flex:1;min-width:190px;border-radius:9px;padding:10px 12px;` +
              (invalidated
                ? "background:#f5e1dc;border:1px solid #e6bcb0"
                : "background:#fbf3e2;border:1px solid #e6cf9e"),
          )}
        >
          <div
            className="mono"
            style={css(
              `font-size:9px;letter-spacing:.06em;font-weight:700;color:${invalidated ? "#8a2f22" : "#7a4f10"}`,
            )}
          >
            {invalidated ? "PLAN STATUS · INVALIDATED" : "PLAN STATUS · UNDER REVIEW"}
          </div>
          <div style={css("font-size:12px;font-weight:600;color:#16262c;margin-top:5px;line-height:1.35")}>
            {invalidated
              ? "rev08 is no longer safe for the recalled lot — no rev09 is invented."
              : "Checking whether rev08 remains valid for LTC-4471."}
          </div>
        </div>
      </div>

      <div style={css("background:#fafbf9;border:1px solid #eef0ea;border-radius:10px;padding:11px 14px")}>
        <div
          className="mono"
          style={css("font-size:9px;letter-spacing:.07em;color:#5f6f74;font-weight:700")}
        >
          AFFECTED COMMITMENTS · LOT LTC-4471
        </div>
        {affected.length === 0 ? (
          <div style={css("font-size:11.5px;color:#5f6f74;margin-top:8px")}>
            No commitment at this boundary references the recalled lot.
          </div>
        ) : (
          affected.map((c) => (
            <div
              key={c.id}
              data-testid="scoped-commitment"
              style={css(
                "display:flex;align-items:center;gap:11px;padding:9px 0;border-top:1px solid #f1f3ef",
              )}
            >
              <span className="mono" style={css("font-size:11.5px;font-weight:700;color:#16262c;width:44px;flex:none")}>
                {c.id}
              </span>
              <span style={css("font-size:12px;color:#3a4a50;flex:1;min-width:0")}>
                {facilityName(c.agency)} · {c.cases} cases
              </span>
              <span
                style={css(
                  "font-size:10px;font-weight:600;border-radius:5px;padding:3px 9px;flex:none;" +
                    (barrier ? "background:#f5e1dc;color:#8a2f22" : "background:#f7ecd6;color:#7a4f10"),
                )}
              >
                {barrier ? "Blocked" : c.stateLabel}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
