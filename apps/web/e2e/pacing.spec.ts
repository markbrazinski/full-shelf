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
