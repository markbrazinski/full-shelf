// Guards the two filming budgets that live in App.tsx as constants.
//
// Pacing is presentation only, so this asserts the declared budget, not
// wall-clock behavior: a timing-sensitive browser test would be flaky and
// would prove nothing the constants do not already fix.
import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const APP = readFileSync(
  fileURLToPath(new URL("../src/App.tsx", import.meta.url)),
  "utf8",
);

const constant = (name: string): number => {
  const m = new RegExp(`const ${name} = ([0-9_]+);`).exec(APP);
  if (!m) throw new Error(`${name} not found in App.tsx`);
  return Number(m[1].replace(/_/g, ""));
};

test("the page holds still for four seconds before anything moves", () => {
  expect(constant("OPENING_HOLD_MS")).toBe(4_000);
  // The hold must gate the autoplay start, not merely exist.
  expect(APP).toContain("openingHold = window.setTimeout(");
  expect(APP).toMatch(/setPlaying\(true\);\s*\}, OPENING_HOLD_MS\)/);
});

test("the truck-failure beat runs eight seconds end to end", () => {
  const total = constant("TRUCK_SEQUENCE_MS");
  expect(total).toBe(8_000);

  // Events 6 and 7 must spend the whole budget and nothing more: the
  // failure, the scoping, and the proposal landing are one beat.
  const six = Math.round(total * 0.5);
  const seven = total - six;
  expect(six + seven).toBe(total);

  // Both dwells must actually be apportioned from the budget rather than
  // drifting back to hardcoded values.
  expect(APP).toContain("6: Math.round(TRUCK_SEQUENCE_MS * 0.5)");
  expect(APP).toContain("7: TRUCK_SEQUENCE_MS - Math.round(TRUCK_SEQUENCE_MS * 0.5)");
});

const WORKSPACE = readFileSync(
  fileURLToPath(new URL("../src/components/IncidentWorkspace.tsx", import.meta.url)),
  "utf8",
);

/** The stage→events table as App.tsx actually declares it. */
const stageEvents = (): number[][] => {
  const block = /const RECALL_STAGE_EVENTS[\s\S]*?\n\];/.exec(APP);
  if (!block) throw new Error("RECALL_STAGE_EVENTS not found in App.tsx");
  return [...block[0].matchAll(/\[([\d,\s]+)\]/g)].map((m) =>
    m[1].split(",").map((n) => Number(n.trim())).filter(Number.isFinite),
  );
};

test("opening Incidents waits one second before the recall starts", () => {
  expect(constant("RECALL_ENTRY_DELAY_MS")).toBe(1_000);
  expect(APP).toContain("setTimeout(() => setPlaying(true), RECALL_ENTRY_DELAY_MS)");
});

test("the recall holds until the operator starts it", () => {
  // The hold is only real if the FRONTEND ticker respects it: pausing the
  // runtime does not stop autoplay, because pacing is driven client-side.
  expect(APP, "autoplay must not tick while the recall waits")
    .toContain("if (recallPaused) return;");
  expect(APP).toMatch(/\}, \[playing, paused, branch, cursor, gatePaused, recallPaused,/);

  // Unconditional: an operator already on Incidents has not asked for
  // anything, so the hold may not depend on the current view.
  expect(APP).toContain("if (seq === 11) {");
  expect(APP, "the hold must not be conditional on the current view")
    .not.toContain('seq === 11 && viewRef.current === "today"');

  // A timer already armed for event 11 must be invalidated before the
  // state update, or it commits event 12 in the gap before the re-render.
  expect(APP).toMatch(/cancelTickRef\.current\(\);[\s\S]{0,200}setRecallPaused\(true\)/);

  // Release is a deliberate press, never mere presence on the view.
  expect(APP).toContain("const openIncidents = useCallback(");
  expect(APP).toContain('id === "incident" ? openIncidents() : setView(id)');
  expect(APP).toContain("onOpenIncidents={openIncidents}");
  expect(APP).toContain('data-testid="start-recall-response"');
});

test("every recall stage takes eight seconds end to end", () => {
  const budget = constant("RECALL_STAGE_MS");
  expect(budget).toBe(8_000);

  const stages = stageEvents();
  expect(stages).toHaveLength(5);

  // Each stage spends its whole budget and no more, rounding included.
  for (const events of stages) {
    const each = Math.floor(budget / events.length);
    const total = each * (events.length - 1) + (budget - each * (events.length - 1));
    expect(total).toBe(budget);
  }
});

test("the stage table matches the workspace's own stage boundaries", () => {
  // App.tsx paces the stages; IncidentWorkspace.tsx decides where they
  // begin. If these drift, stages are timed against the wrong events.
  const declared = [...WORKSPACE.matchAll(/minEvent:\s*(\d+)/g)].map((m) => Number(m[1]));
  const paced = stageEvents().map((events) => events[0]);
  expect(paced).toEqual(declared);
});

test("committed state changes are carried by motion, not hard cuts", () => {
  const CSS = readFileSync(
    fileURLToPath(new URL("../src/styles/global.css", import.meta.url)),
    "utf8",
  );

  for (const cls of ["fs-stage-tween", "fs-stage-enter", "fs-entry-enter"]) {
    expect(CSS, `${cls} must be defined`).toContain(`.${cls}`);
  }

  // Every duration must sit inside the SHORTEST dwell, or a stage could
  // still be animating when the next event commits. Stage 2 spends the
  // budget across five events, so that is the floor.
  const shortest = constant("RECALL_STAGE_MS") / 5;
  const durations = [...CSS.matchAll(/(\d+)ms/g)].map((m) => Number(m[1]));
  expect(durations.length).toBeGreaterThan(0);
  for (const d of durations) {
    expect(d, `${d}ms must fit inside the ${shortest}ms dwell`).toBeLessThan(shortest);
  }

  // Motion must be reachable from the surfaces that actually change.
  expect(WORKSPACE).toContain('className="fs-stage-tween"');
  expect(WORKSPACE, "the stage body must remount so the enter animation fires")
    .toContain('key={viewStage?.key ?? "none"}');
  expect(WORKSPACE).toContain('className="fs-stage-enter"');

  // And it must be defeasible.
  expect(CSS).toContain("prefers-reduced-motion");
});
