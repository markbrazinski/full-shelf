// =====================================================================
// Full Shelf v6.1 — acceptance verification at 1600x900
// ---------------------------------------------------------------------
// Runs against the REAL localhost replay server and a real Vite dev
// server in deterministic mode — never a mock.
//
// Every assertion is a CONTRACT claim, not a styling claim: canonical
// quantities, absence of GPS language, projection-derived incident
// counts, the Saturday unavailable state, and the fixture staying out
// of the runtime path.
// =====================================================================

import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const SHOTS = path.resolve("e2e/screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

const LOADING = "text=Loading control plane…";

async function settle(page: Page) {
  await page.waitForSelector(LOADING, { state: "detached", timeout: 15_000 });
}

async function open(page: Page) {
  await page.goto("/");
  await settle(page);
}

/** Film mode exposes one forward-only presenter gesture and no beat strip. */
async function advance(page: Page, steps = 1) {
  for (let i = 0; i < steps; i += 1) {
    await page.keyboard.press("ArrowRight");
    // Give React a turn to mount the loading boundary before waiting for it.
    await page.waitForTimeout(20);
    await settle(page);
  }
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false });
}

// --------------------------------------------------------------- Friday

test("01 · Friday healthy shows rev07 commitments and a quiet sidecar", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("auth-rev")).toHaveText("rev07");
  await expect(page.getByTestId("clock")).toHaveText("08:05");
  await expect(page.locator("body")).toContainText("O201");
  // No incident has been reported at 08:05, so no badge exists.
  await expect(page.getByTestId("incident-badge")).toHaveCount(0);
  await expect(page.getByTestId("sidecar-quiet")).toBeVisible();
  const map = page.getByTestId("today-map");
  const manifests = page.getByTestId("truck-manifests");
  await expect(map).toBeVisible();
  await expect(manifests).toBeVisible();
  const mapBox = await map.boundingBox();
  const manifestBox = await manifests.boundingBox();
  expect(mapBox!.y + mapBox!.height).toBeLessThanOrEqual(900);
  expect(manifestBox!.y + manifestBox!.height).toBeLessThanOrEqual(900);
  await expect(manifests).toContainText("COMMITTED MANIFEST ORDER");
  await expect(page.locator("main")).not.toContainText("OPEN OBLIGATIONS");
  await expect(page.locator("main")).not.toContainText("CONTEXTUAL DISPATCH VIEW");
  await expect(page.locator("[data-testid^='moment-']")).toHaveCount(0);
  await expect(page.locator("[data-presentation-mode='film']")).toBeVisible();
  await shot(page, "v6-01-friday-healthy");
});

test("01a · replay diagnostics require explicit local debug mode", async ({ page }) => {
  await page.goto("/?debug=1");
  await settle(page);
  await expect(page.locator("[data-presentation-mode='debug']")).toBeVisible();
  await expect(page.getByTestId("moment-healthy")).toBeVisible();
  await expect(page.getByTestId("moment-fault")).toBeVisible();
  await expect(page.getByTestId("moment-proposed")).toBeVisible();
  await expect(page.getByTestId("moment-updated")).toBeVisible();
});

test("02 · disruption is in place: same shell, rev08, incident badge appears", async ({ page }) => {
  await open(page);
  const navBefore = await page.getByTestId("nav-today").boundingBox();

  await advance(page, 3);

  await expect(page.getByTestId("auth-rev")).toHaveText("rev08");
  // The shell stays put: disruption happens inside the workspace, so the nav
  // keeps its position and size. Tolerates sub-pixel reflow of the banner
  // above it; what matters is that the shell does not relayout.
  const navAfter = await page.getByTestId("nav-today").boundingBox();
  expect(navAfter!.x).toBe(navBefore!.x);
  expect(navAfter!.width).toBe(navBefore!.width);
  expect(Math.abs(navAfter!.y - navBefore!.y)).toBeLessThanOrEqual(2);
  // Presenter navigation is forward-only and stops at the committed update.
  await advance(page);
  await expect(page.getByTestId("auth-rev")).toHaveText("rev08");
  await expect(page.getByTestId("clock")).toHaveText("08:24");
  await shot(page, "v6-02-friday-disrupted");
});

test("03 · incident badge is derived from the projection, not the view", async ({ page }) => {
  await open(page);
  // Today + healthy: no incident exists at this boundary.
  await expect(page.getByTestId("incident-badge")).toHaveCount(0);

  // Opening the Incidents view must NOT conjure a badge by itself; the
  // count comes from the contract's incidents at that boundary.
  await page.getByTestId("nav-incident").click();
  await settle(page);
  const badge = page.getByTestId("incident-badge");
  await expect(badge).toBeVisible();
  // One open incident: the recall. The truck failure resolved at 08:24 and
  // must NOT be counted, which is the whole point of deriving this.
  await expect(badge).toHaveText("1");
  const statuses = page.getByTestId("incident-status");
  await expect(statuses.filter({ hasText: "INC-2210" })).toContainText("RESOLVED");
  await expect(statuses.filter({ hasText: "INC-2231" })).toContainText(/SCOPING|CONTAINMENT|PARTIALLY_CONTAINED/);

  // At the Response boundary the recall has reached its terminal state.
  await page.getByTestId("tab-response").click();
  await settle(page);
  await expect(page.getByTestId("incident-badge")).toHaveText("1");
  await expect(page.getByTestId("incident-status").filter({ hasText: "INC-2231" }))
    .toContainText("PARTIALLY_CONTAINED");
});

// ------------------------------------------------------------- Incident

test("04 · recall Scope", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);
  await page.getByTestId("tab-scope").click();
  await settle(page);
  await expect(page.locator("body")).toContainText("LTC-4471");
  await expect(page.locator("body")).toContainText(/Model Armor/i);
  await shot(page, "v6-04-incident-scope");
});

test("05 · Custody holds the canonical 96 / 88 / 8", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);
  await page.getByTestId("tab-custody").click();
  await settle(page);
  const body = page.locator("body");
  await expect(body).toContainText("96");
  await expect(body).toContainText("88");
  await expect(body).toContainText("8");
  await shot(page, "v6-05-incident-custody");
});

test("06 · Response holds 40 recovered, 20 short, and the canonical refusal", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);
  await page.getByTestId("tab-response").click();
  await settle(page);
  const body = page.locator("body");
  await expect(body).toContainText("40");
  await expect(body).toContainText("20");
  await expect(body).toContainText(/DENIED/);
  await expect(body).toContainText(/0 MUTATIONS/i);
  await shot(page, "v6-06-incident-response");
});

test("07 · Evidence opens the Execution Record", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);
  await page.getByTestId("tab-evidence").click();
  await settle(page);
  await page.getByRole("button", { name: /Execution Record/i }).first().click();
  await expect(page.locator("body")).toContainText(/EXECUTION RECORD/i);
  await shot(page, "v6-07-incident-evidence");
});

test("07a · vague partner response is denied with 88 of 96 and an open work item", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);
  await page.getByTestId("tab-vague").click();
  await settle(page);
  const proof = page.getByTestId("partner-evidence-vague");
  await expect(proof).toContainText("We pulled the remaining lettuce");
  await expect(proof).toContainText("DENIED");
  await expect(proof).toContainText("Domain mutations");
  await expect(proof).toContainText("0");
  await expect(proof).toContainText("88/96 → 88/96");
  await expect(proof).toContainText("OPEN → OPEN");
  await expect(proof).toContainText("ISOLATED SELECTED PROOF");
  await shot(page, "partner-evidence-vague");
});

test("07b · complete partner response applies exactly two domain mutations", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);
  await page.getByTestId("tab-complete").click();
  await settle(page);
  const proof = page.getByTestId("partner-evidence-complete");
  await expect(proof).toContainText("LTC-4471 · 8 cases");
  await expect(proof).toContainText("APPLIED");
  await expect(proof).toContainText("96/96");
  await expect(proof).toContainText("OPEN → COMPLETED");
  await expect(proof).toContainText("invocation fixture-invocation");
  await shot(page, "partner-evidence-complete");
});

// -------------------------------------------------------------- History

test("08 · History is read-only", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-history").click();
  await settle(page);
  await expect(page.locator("body")).toContainText(/read-only/i);
  await shot(page, "v6-08-history");
});

// ------------------------------------------------------------- Saturday

test("09 · Saturday candidate plan is contract-backed", async ({ page }) => {
  await open(page);
  await page.getByTestId("day-sat").click();
  await settle(page);

  await expect(page.getByTestId("saturday-candidate-map")).toBeVisible();
  const manifests = page.getByTestId("candidate-manifest");
  await expect(manifests.first()).toBeVisible();
  await expect(manifests.first()).toContainText("CANDIDATE");

  // 18 + 22 = 40 scheduled; Agency 03's 20 stay explicitly unassigned.
  const body = page.locator("body");
  await expect(body).toContainText("18");
  await expect(body).toContainText("22");
  await expect(page.getByTestId("unassigned-demand")).toContainText("20");
  await expect(page.getByTestId("unassigned-demand")).toContainText(/AGENCY-03/i);

  // A draft makes no activation or delivery-feasibility claim.
  await expect(body).not.toContainText(/Activate/i);
  await expect(body).not.toContainText(/will be delivered/i);
  await shot(page, "v6-09-saturday-candidate");
});

test("10 · Saturday renders the unavailable state when the contract has no draft", async ({ page }) => {
  // Serve a draft-free projection so the unavailable path is genuinely
  // exercised, rather than passing because the fixture happened to be empty.
  await page.route("**/projections/demo-beats**", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    delete body.next_day_draft;
    await route.fulfill({ response: res, body: JSON.stringify(body) });
  });

  await open(page);
  await page.getByTestId("day-sat").click();
  await settle(page);

  await expect(page.getByTestId("saturday-unavailable")).toBeVisible();
  await expect(page.getByTestId("saturday-status-chip")).toContainText(/UNAVAILABLE/i);

  // No routes, manifests, assignments, loads, or lots are drawn.
  await expect(page.getByTestId("saturday-candidate-map")).toHaveCount(0);
  await expect(page.getByTestId("candidate-manifest")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("LTC-5090");
  await shot(page, "v6-10-saturday-unavailable");
});

// ------------------------------------------------------- datasource fail

test("11 · datasource failure shows the error surface and Reconnect retries", async ({ page }) => {
  let fail = true;
  await page.route("**/projections/demo-beats**", async (route) => {
    if (fail) return route.abort("failed");
    return route.fallback();
  });

  await page.goto("/");
  await expect(page.getByTestId("connection-error")).toBeVisible();
  // Nothing stale is shown behind the error.
  await expect(page.locator("body")).not.toContainText("O201");
  await shot(page, "v6-11-connection-error");

  // Reconnect performs a REAL retry: with the fault cleared it recovers.
  fail = false;
  await page.getByTestId("reconnect").click();
  await settle(page);
  await expect(page.getByTestId("connection-error")).toHaveCount(0);
  await expect(page.locator("body")).toContainText("O201");
  await shot(page, "v6-12-reconnected");
});

test("11a · malformed projection fails closed without stale operational data", async ({ page }) => {
  await page.route("**/projections/demo-beats**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ projection_boundary: { mode: "MALFORMED_TEST" } }),
  }));
  await page.goto("/");
  await expect(page.getByTestId("connection-error")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("O201");
  await shot(page, "v6-18-malformed-projection");
});

// ------------------------------------------------------------------ map

test("12 · map fallback renders without a Maps key", async ({ page }) => {
  await open(page);
  await advance(page, 3);
  // No key is configured in verification, so the SVG schematic is shown.
  await expect(page.getByTestId("dispatch-svg-schematic")).toBeVisible();
  await expect(page.getByTestId("map-mode-label")).toContainText("DETERMINISTIC SCHEMATIC");
  await expect(page.getByTestId("map-mode-label")).toContainText("NOT LIVE GPS");
  await shot(page, "v6-13-map-fallback");
});

test("13 · map degrades to the schematic when Maps fails to load", async ({ page }) => {
  // A forced FAKE key exercises the unauthorized-key path. A real key is
  // never read from or written to the page.
  await page.addInitScript(() => {
    (globalThis as { __FS_FORCE_MAP_KEY?: string }).__FS_FORCE_MAP_KEY = "fake-invalid-key";
  });
  await page.route("https://maps.googleapis.com/**", (route) => route.abort("failed"));

  await open(page);
  await advance(page, 3);
  await expect(page.getByTestId("dispatch-svg-schematic")).toBeVisible();
  await expect(page.getByTestId("map-mode-label")).toContainText("DETERMINISTIC SCHEMATIC");
  await shot(page, "v6-14-map-degraded");
});

test("13a · configured Maps API paints before the Google map is accepted", async ({ page }) => {
  await page.addInitScript(() => {
    (globalThis as { __FS_FORCE_MAP_KEY?: string }).__FS_FORCE_MAP_KEY = "fake-structural-valid-key";
  });
  await page.route("https://maps.googleapis.com/**", (route) => route.fulfill({
    status: 200,
    contentType: "application/javascript",
    body: `
      window.google = { maps: {
        SymbolPath: { CIRCLE: "circle" },
        LatLngBounds: class { constructor(){ this.empty = true; } extend(){ this.empty = false; } isEmpty(){ return this.empty; } },
        Map: class { constructor(el){ const tile = document.createElement("img"); tile.src = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="; el.appendChild(tile); } fitBounds(){} },
        Marker: class { setPosition(){} setTitle(){} setIcon(){} }, Polyline: class {},
        event: { addListenerOnce(_map, name, cb){ if (name === "tilesloaded") setTimeout(cb, 0); } }
      }};
    `,
  }));
  await open(page);
  await expect(page.getByTestId("planned-dispatch-map")).toBeVisible();
  await expect(page.getByTestId("map-mode-label")).toContainText("GOOGLE MAPS");
  await expect(page.getByTestId("map-mode-label")).toContainText("SIMULATED TELEMETRY");
  await expect(page.getByTestId("map-mode-label")).toContainText("NOT LIVE GPS");
  await expect(page.getByTestId("dispatch-svg-schematic")).toHaveCount(0);
  await shot(page, "v6-15-google-maps-structural");
});

test("13b · an API auth rejection falls back without a grey panel", async ({ page }) => {
  await page.addInitScript(() => {
    (globalThis as { __FS_FORCE_MAP_KEY?: string }).__FS_FORCE_MAP_KEY = "fake-auth-rejected-key";
  });
  await page.route("https://maps.googleapis.com/**", (route) => route.fulfill({
    status: 200,
    contentType: "application/javascript",
    body: "window.gm_authFailure && window.gm_authFailure();",
  }));
  await open(page);
  await expect(page.getByTestId("dispatch-svg-schematic")).toBeVisible();
  await expect(page.getByTestId("map-mode-label")).toContainText("DETERMINISTIC SCHEMATIC");
  await shot(page, "v6-16-map-auth-fallback");
});

test("13c · a loaded API with no painted tiles falls back", async ({ page }) => {
  await page.addInitScript(() => {
    (globalThis as { __FS_FORCE_MAP_KEY?: string }).__FS_FORCE_MAP_KEY = "fake-no-tiles-key";
  });
  await page.route("https://maps.googleapis.com/**", (route) => route.fulfill({
    status: 200,
    contentType: "application/javascript",
    body: `
      window.google = { maps: {
        SymbolPath: { CIRCLE: "circle" },
        LatLngBounds: class { constructor(){ this.empty = true; } extend(){ this.empty = false; } isEmpty(){ return this.empty; } },
        Map: class { fitBounds(){} }, Marker: class { setPosition(){} setTitle(){} setIcon(){} }, Polyline: class {},
        event: { addListenerOnce(){} }
      }};
    `,
  }));
  await open(page);
  await expect(page.getByTestId("dispatch-svg-schematic")).toBeVisible({ timeout: 6_000 });
  await expect(page.getByTestId("map-mode-label")).toContainText("DETERMINISTIC SCHEMATIC");
  await shot(page, "v6-17-map-tiles-fallback");
});

// ------------------------------------------------------------- integrity

test("14 · no live-GPS claim and no future-state leakage on any surface", async ({ page }) => {
  await open(page);
  for (const [nav, label] of [
    ["nav-today", "today"],
    ["nav-incident", "incident"],
    ["nav-history", "history"],
  ] as const) {
    await page.getByTestId(nav).click();
    await settle(page);
    const text = (await page.locator("body").innerText()).toLowerCase();

    // Positive GPS claims are forbidden; the negation is required copy.
    const claims = text.match(/\blive gps\b|\breal-?time gps\b|\bcurrent position\b/g) ?? [];
    for (const c of claims) {
      const i = text.indexOf(c);
      expect(text.slice(Math.max(0, i - 12), i)).toMatch(/not\s+$/);
    }
    // Saturday must never leak into a Friday surface.
    if (label !== "history") {
      expect(text).not.toContain("plan-2026-08-15");
    }
    // Agents never show a transient state.
    expect(text).not.toMatch(/\brunning\b/);
  }
});

test("15 · the design fixture never reaches the runtime path", async ({ page }) => {
  const sources: string[] = [];
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("/src/") || u.includes("/assets/")) sources.push(u);
  });
  await open(page);
  expect(sources.filter((u) => /FixtureDataSource/i.test(u))).toHaveLength(0);
});

test("15a · fixed as_of and deterministic telemetry repeat after refresh", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const firstResponse = page.waitForResponse((r) => r.url().includes("/projections/demo-beats"));
  await open(page);
  const first = await firstResponse;
  const firstUrl = first.url();
  const firstBody = await first.text();
  await advance(page);
  const firstTelemetry = await page.getByTestId("telemetry-strip").innerText();
  const firstDrawing = await page.getByTestId("dispatch-svg-schematic").innerHTML();

  const secondResponse = page.waitForResponse((r) => r.url().includes("/projections/demo-beats"));
  await page.reload();
  await settle(page);
  const second = await secondResponse;
  expect(second.url()).toBe(firstUrl);
  expect(await second.text()).toBe(firstBody);
  await advance(page);
  expect(await page.getByTestId("telemetry-strip").innerText()).toBe(firstTelemetry);
  expect(await page.getByTestId("dispatch-svg-schematic").innerHTML()).toBe(firstDrawing);
});

// ------------------------------------------------- event -> proposal -> approval

test("16 · the fault, the proposal, and an unchanged active plan", async ({ page }) => {
  await open(page);
  await shot(page, "story-1-healthy-today");

  await advance(page);

  // The alarm is a reported mechanical event with its source and time.
  const alarm = page.getByTestId("refrigeration-alarm");
  await expect(alarm).toBeVisible();
  await expect(alarm).toContainText(/SIMULATED FLEET TELEMATICS/i);
  await expect(alarm).toContainText(/not derived from position/i);
  await shot(page, "story-2-refrigeration-failure");

  // The proposal is a later committed boundary in the same stable shell.
  await expect(page.getByTestId("repair-proposal")).toHaveCount(0);
  await advance(page);

  // The proposal is what the agents propose, not an authorization.
  await expect(page.getByTestId("proposal-authority")).toContainText(/AGENT PROPOSAL/i);
  await expect(page.getByTestId("proposal-reroute")).toContainText("O202");
  await expect(page.getByTestId("proposal-reroute")).toContainText("22");
  await expect(page.getByTestId("proposal-reroute")).toContainText("58");
  await expect(page.getByTestId("proposal-pickup")).toContainText("O203");
  await expect(page.getByTestId("proposal-pickup")).toContainText(/partner pickup/i);

  // The active plan has NOT changed while the proposal is pending.
  await expect(page.getByTestId("auth-rev")).toHaveText("rev07");
  await expect(page.locator("body")).toContainText("Truck 1");
  await shot(page, "story-3-proposal-awaiting-approval");
});

test("17 · approving commits once and the proposal stops being offered", async ({ page }) => {
  let approvals = 0;
  await page.route("**/approvals/approve-and-activate", async (route) => {
    approvals += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ACTIVATED", proposed_revision: "rev08" }),
    });
  });

  await open(page);
  await advance(page, 2);
  await expect(page.getByTestId("approve-update")).toBeVisible();

  await page.getByTestId("approve-update").click();
  await settle(page);

  // Exactly one approval was submitted, and the plan updated in place.
  expect(approvals).toBe(1);
  await expect(page.getByTestId("auth-rev")).toHaveText("rev08");
  // The proposal was answered, so it is no longer offered.
  await expect(page.getByTestId("repair-proposal")).toHaveCount(0);
  await expect(page.getByTestId("approve-update")).toHaveCount(0);
  await shot(page, "story-4-updated-plan-committed");
});

test("18 · a rejected approval changes nothing", async ({ page }) => {
  await page.route("**/approvals/approve-and-activate", (route) =>
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: "CANONICAL_REVISION_TRANSITION_REQUIRED" }),
    }),
  );

  await open(page);
  await advance(page, 2);
  await page.getByTestId("approve-update").click();

  await expect(page.getByTestId("approval-error")).toBeVisible();
  await expect(page.getByTestId("approval-error")).toContainText(/did not change/i);
  // Still pending, still rev07: nothing was committed.
  await expect(page.getByTestId("auth-rev")).toHaveText("rev07");
  await expect(page.getByTestId("repair-proposal")).toBeVisible();
});

test("19 · no approval control exists once the update is committed", async ({ page }) => {
  await open(page);
  await advance(page, 3);
  await expect(page.getByTestId("repair-proposal")).toHaveCount(0);
  await expect(page.getByTestId("approve-update")).toHaveCount(0);
  await expect(page.getByTestId("auth-rev")).toHaveText("rev08");
});

test("20 · recall intake states its source and keeps Model Armor a boundary", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);
  await page.getByTestId("tab-scope").click();
  await settle(page);

  const body = page.locator("body");
  await expect(body).toContainText(/Model Armor/i);
  // Never a claim of continuous FDA monitoring.
  await expect(body).not.toContainText(/monitors the FDA/i);
  await expect(body).not.toContainText(/monitoring the FDA/i);
  await shot(page, "story-5-recall-intake");
});

test("21 · custody exception and the governed refusal", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);

  await page.getByTestId("tab-custody").click();
  await settle(page);
  await expect(page.locator("body")).toContainText("96");
  await shot(page, "story-6-custody-exception");

  await page.getByTestId("tab-response").click();
  await settle(page);
  const body = page.locator("body");
  await expect(body).toContainText(/DENIED/);
  // DECLARE_CONTAINED is not a real backend command and must never render.
  await expect(body).not.toContainText(/DECLARE_CONTAINED/);
  await shot(page, "story-7-recovery-and-refusal");
});

test("22 · custody and recovery lead with projected benefit", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);

  await page.getByTestId("tab-custody").click();
  await settle(page);
  // The headline is composed from projected quantities, so it must agree
  // with the canonical custody totals rather than be prose.
  const custody = page.getByTestId("custody-headline");
  await expect(custody).toContainText("96");
  await expect(custody).toContainText("8");
  await expect(custody).toContainText(/downstream site/i);
  // Human-readable roles are present alongside projected identities.
  await expect(page.locator("body")).toContainText(/Distribution site|Partner pantry|In transit/);

  await page.getByTestId("tab-response").click();
  await settle(page);
  const recovery = page.getByTestId("recovery-headline");
  await expect(recovery).toContainText("40");
  await expect(recovery).toContainText(/programs/i);
  // The gap stays visible rather than being filled.
  await expect(page.locator("body")).toContainText("20");
});

test("23 · the recall source is a delivered event, not claimed monitoring", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);
  await page.getByTestId("tab-scope").click();
  await settle(page);

  const source = page.getByTestId("recall-source");
  await expect(source).toBeVisible();
  await expect(source).toContainText(/Regulatory feed/i);
  await expect(source).toContainText(/FDA-format notice/i);
  // The committed arrival time, read from the ledger. The canonical seed
  // records the incident at 09:36; 09:35 is the boundary just before it.
  await expect(source).toContainText("09:36");
  // Never a claim of continuous monitoring or polling.
  const text = (await page.locator("body").innerText()).toLowerCase();
  expect(text).not.toContain("monitors the fda");
  expect(text).not.toContain("continuously monitor");
  expect(text).not.toContain("polling the fda");
});

test("24 · the refusal narrates the real backend sequence", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-incident").click();
  await settle(page);
  await page.getByTestId("tab-response").click();
  await settle(page);

  const body = page.locator("body");
  // The real sequence: eligibility check -> RECORD_REFUSAL -> DENIED.
  await expect(body).toContainText(/closure eligibility check/i);
  await expect(body).toContainText(/RECORD_REFUSAL/);
  await expect(body).toContainText(/DENIED/);
  await expect(body).toContainText(/0 MUTATIONS/i);
  await expect(body).toContainText(/PARTIALLY_CONTAINED/);
  // The fictional command must never appear.
  await expect(body).not.toContainText(/DECLARE_CONTAINED/);
});
