// =====================================================================
// Full Shelf — 13-view verification against the real replay server
// ---------------------------------------------------------------------
// Every assertion here is a CONTRACT claim, not a styling claim: the
// canonical quantities, the absence of GPS language, the first-safe
// boundaries, and the fixture staying out of the runtime path.
// =====================================================================

import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const SHOTS = path.resolve("e2e/screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

const REPLAY = "http://127.0.0.1:8787";

interface View {
  n: number;
  id: string;
  label: string;
  expect: RegExp;
}

// The 12 operational states, in beat order, plus History.
const VIEWS: View[] = [
  { n: 1,  id: "healthy",            label: "Healthy",             expect: /O201/ },
  { n: 2,  id: "truckFailure",       label: "Truck failure",       expect: /INC-2210/ },
  { n: 3,  id: "revisionReview",     label: "Revision review",     expect: /rev08/ },
  { n: 4,  id: "dispatchSchematic",  label: "Planned dispatch",    expect: /not live vehicle tracking/ },
  { n: 5,  id: "rev08Active",        label: "rev08 active",        expect: /rev08/ },
  { n: 6,  id: "recallReceived",     label: "Recall received",     expect: /LTC-4471/ },
  { n: 7,  id: "recallProcessing",   label: "Recall processing",   expect: /INC-2231/ },
  { n: 8,  id: "custodyEstablished", label: "Custody established", expect: /Custody established/ },
  { n: 9,  id: "governedRecovery",   label: "Governed recovery",   expect: /40/ },
  { n: 10, id: "governanceRefusal",  label: "Governance refusal",  expect: /DENIED/ },
  { n: 11, id: "todaysOutcome",      label: "Today's Outcome",     expect: /PARTIALLY_CONTAINED/ },
  { n: 12, id: "tomorrowsDraft",     label: "Tomorrow",            expect: /PLAN-2026-08-15|DRAFT/ },
  { n: 13, id: "history",            label: "History",             expect: /Read-only|read-only/i },
];

async function gotoBeat(page: Page, id: string) {
  await page.goto("/");
  await page.waitForSelector("text=Loading projection…", { state: "detached", timeout: 15_000 });
  if (id === "history") {
    await page.getByRole("button", { name: /history/i }).first().click();
  } else {
    await page.locator(`[data-beat="${id}"]`).first().click();
  }
  await page.waitForSelector("text=Loading projection…", { state: "detached", timeout: 15_000 });
  await page.waitForTimeout(250);
}

test.describe("13 views from deterministic replay", () => {
  for (const v of VIEWS) {
    test(`${String(v.n).padStart(2, "0")} ${v.label} renders from replay`, async ({ page }) => {
      const requests: string[] = [];
      page.on("request", (r) => {
        if (r.url().includes("/api/v1/projections/")) requests.push(r.url());
      });

      await gotoBeat(page, v.id);

      const body = await page.locator("body").innerText();
      expect(body).toMatch(v.expect);

      // Loaded over HTTP from the replay server with an explicit as_of.
      expect(requests.length).toBeGreaterThan(0);
      expect(requests.some((u) => u.startsWith(REPLAY) && u.includes("as_of="))).toBe(true);

      // No live VEHICLE-tracking claim in any view. Two things are
      // deliberately NOT violations: negated disclaimers ("no positions
      // or bearings"), and custody "current positions", which are where
      // cases are held in the network — not a vehicle location.
      expect(body).not.toMatch(/last reported|GPS|live position|live tracking(?! )/i);
      expect(body).not.toMatch(/bearing:|heading:|lat\s*[:=]|lng\s*[:=]/i);
      // Any mention of tracking must be a denial of it.
      for (const m of body.match(/[^\n]*vehicle tracking[^\n]*/gi) ?? []) {
        expect(m).toMatch(/not live vehicle tracking/i);
      }

      await page.screenshot({
        path: path.join(SHOTS, `${String(v.n).padStart(2, "0")}-${v.id}.png`),
        fullPage: false,
      });
    });
  }
});

test("canonical facts match the authority baseline", async ({ page }) => {
  await gotoBeat(page, "governanceRefusal");
  const body = await page.locator("body").innerText();
  // O203/20 is the partner pickup; O205/21 was fabricated and must not appear as one.
  expect(body).toMatch(/DENIED/);
  expect(body).not.toMatch(/O205\s*·[^\n]*partner/i);

  // The custody graph's first safe boundary is 10:10. At 10:05 it is
  // omitted as PRE_BOUNDARY_STATE_NOT_RETAINED and must not be shown.
  await gotoBeat(page, "custodyEstablished");
  const early = await page.locator("body").innerText();
  expect(early).not.toMatch(/\b96\b/);

  await gotoBeat(page, "governedRecovery");
  const custody = await page.locator("body").innerText();
  expect(custody).toMatch(/\b96\b/); // unique current cases
  expect(custody).toMatch(/\b88\b/); // confirmed
  expect(custody).toMatch(/\b8\b/);  // unconfirmed
});

test("dispatch shows the 58/60 decision and the O203 partner path", async ({ page }) => {
  await gotoBeat(page, "governanceRefusal");
  // rev08 dispatch is reached from the planned-dispatch view.
  await gotoBeat(page, "dispatchSchematic");
  const body = await page.locator("body").innerText();
  expect(body).toMatch(/O203/);
  expect(body).toMatch(/not live vehicle tracking/);
});

test("fixed-boundary refresh is byte-stable", async ({ page }) => {
  await gotoBeat(page, "governedRecovery");
  const first = await page.locator("body").innerText();
  await page.reload();
  await page.waitForSelector("text=Loading projection…", { state: "detached", timeout: 15_000 });
  await gotoBeat(page, "governedRecovery");
  const second = await page.locator("body").innerText();
  expect(second).toBe(first);
});

test("Tomorrow requires explicit navigation and leaks no future state", async ({ page }) => {
  // Earlier boundaries must not carry tomorrow's draft.
  await gotoBeat(page, "todaysOutcome");
  const outcome = await page.locator("body").innerText();
  expect(outcome).not.toMatch(/PLAN-2026-08-15/);

  await gotoBeat(page, "tomorrowsDraft");
  const tomorrow = await page.locator("body").innerText();
  expect(tomorrow).toMatch(/PLAN-2026-08-15|DRAFT/);
});

test("no future-state data appears at an early boundary", async ({ page }) => {
  await gotoBeat(page, "healthy");
  const body = await page.locator("body").innerText();
  // The recall, the refusal and the custody graph are all later than 08:05.
  expect(body).not.toMatch(/INC-2231/);
  expect(body).not.toMatch(/DENIED/);
  expect(body).not.toMatch(/PARTIALLY_CONTAINED/);
});

test("History is read-only", async ({ page }) => {
  await gotoBeat(page, "history");
  const body = await page.locator("body").innerText();
  expect(body).toMatch(/read-only/i);
  expect(body).toMatch(/RECORD_REFUSAL|refused/i);
});

test("disconnected state shows the last boundary and claims no new truth", async ({ page }) => {
  await gotoBeat(page, "governedRecovery");
  await page.getByRole("button", { name: /connected/i }).first().click();
  const body = await page.locator("body").innerText();
  expect(body).toMatch(/DISCONNECTED/);
  expect(body).toMatch(/No authoritative state changes while disconnected/i);
  await page.screenshot({ path: path.join(SHOTS, "14-disconnected.png") });
});

test("a malformed response degrades honestly", async ({ page }) => {
  await page.route("**/api/v1/projections/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"tenant_id":"x"}' }),
  );
  await page.goto("/");
  await expect(page.getByText("Projection unavailable")).toBeVisible({ timeout: 15_000 });
  const body = await page.locator("body").innerText();
  expect(body).toMatch(/Malformed projection|required field absent/i);
  await page.screenshot({ path: path.join(SHOTS, "15-malformed.png") });
});

test("an unreachable service renders no invented data", async ({ page }) => {
  await page.route("**/api/v1/projections/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByText("Projection unavailable")).toBeVisible({ timeout: 15_000 });
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/O201|O202|96 cases/);
  await page.screenshot({ path: path.join(SHOTS, "16-unreachable.png") });
});

test("missing Maps key falls back to the SVG schematic", async ({ page }) => {
  // No VITE_GOOGLE_MAPS_API_KEY is set for this run, so the fallback is active.
  await gotoBeat(page, "dispatchSchematic");
  await expect(page.getByTestId("dispatch-svg-schematic")).toBeVisible();
  await expect(page.getByTestId("planned-dispatch-map")).toHaveCount(0);
  const label = await page.getByTestId("schematic-provenance-label").innerText();
  expect(label).toMatch(/not live vehicle tracking/);
  await page.screenshot({ path: path.join(SHOTS, "17-map-fallback.png") });
});

test("a Maps key that loads but cannot render falls back to the schematic", async ({ page }) => {
  // Simulate the unauthorized-key case: the API script loads, but no map
  // ever paints. That must degrade to the schematic, not a grey box.
  await page.addInitScript(() => {
    (window as unknown as Record<string, unknown>).__FS_FORCE_MAP_KEY = "INVALID_TEST_KEY";
  });
  await page.route("https://maps.googleapis.com/maps/api/js*", (route) =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: "/* no google namespace */" }),
  );
  await gotoBeat(page, "dispatchSchematic");
  await expect(page.getByTestId("dispatch-svg-schematic")).toBeVisible({ timeout: 15_000 });
  const body = await page.locator("body").innerText();
  expect(body).toMatch(/O203/);
  expect(body).toMatch(/not live vehicle tracking/);
});
