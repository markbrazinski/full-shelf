// =====================================================================
// Full Shelf — golden journey acceptance
// ---------------------------------------------------------------------
// Exercises the REAL React UI against the REAL Golden Runtime Controller
// on 127.0.0.1:8788. No mock, no fixture, no stub.
//
// This asserts UI BEHAVIOR, not cursor or clock progression. Every check
// below reads a rendered surface an operator would actually see:
// the approval gate and its visible action, the event-11 hold and its
// release, distinct advisory/committed recovery, the two evidence
// branches and the canonical restoration after each, and Saturday's
// availability boundary.
//
// Screenshots are captured at 1600×900.
//
// An ORDINARY run writes them to the gitignored Playwright output
// directory, so running the suite never dirties the repository. Writing
// the curated set under e2e/screenshots/golden/ requires an explicit
// opt-in:
//
//     npm run test:golden:update
//     # or: UPDATE_GOLDEN_SCREENSHOTS=1 npx playwright test …
// =====================================================================

import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

/**
 * Curated frames are only rewritten under an explicit opt-in. Without it
 * captures land in test-results/, which .gitignore covers, so a normal
 * `npm test` leaves `git status --porcelain` empty.
 */
const UPDATE_GOLDEN = process.env.UPDATE_GOLDEN_SCREENSHOTS === "1";
const SHOTS = UPDATE_GOLDEN ? "e2e/screenshots/golden" : "test-results/golden-journey";
const RUNTIME = "http://127.0.0.1:8788";

// The runtime autoplays at 900ms; 25 events plus approval needs headroom.
test.setTimeout(180_000);

test.beforeAll(() => {
  mkdirSync(SHOTS, { recursive: true });
  if (!UPDATE_GOLDEN) {
    console.log(`[golden] captures -> ${SHOTS} (gitignored). Set UPDATE_GOLDEN_SCREENSHOTS=1 to refresh the curated set.`);
  }
});

/**
 * Capture a film frame.
 *
 * Waits for the map surface to settle first: a Google basemap must report
 * genuinely painted tiles, and the truthful schematic must be present in
 * its place. Neither a half-painted map nor a loading surface may ever
 * reach a captured frame.
 */
async function shot(page: Page, name: string) {
  await expectMapSettled(page);
  await settleMotion(page);
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
}

/**
 * Hold until the stage-entrance and rail-entry motion has finished.
 *
 * The config asks for reducedMotion "reduce", but that emulation does not
 * reach the page in this Chromium build — the media query reports false and
 * the enter animations run anyway. A frame taken mid-tween catches the
 * dominant panel part-way through fs-rise, at partial opacity, which is a
 * capture artefact rather than any state an operator reaches. Waiting on the
 * running animations is the honest fix and it is correct either way: with
 * motion genuinely disabled there is nothing to await.
 */
async function settleMotion(page: Page) {
  await page.evaluate(async () => {
    // fs-pulse and fs-spin loop forever and never resolve `finished`, so
    // only the one-shot enter animations are awaited. They are all well
    // under the shortest dwell, but the race keeps a capture from ever
    // hanging on an animation that will not end.
    const finite = document
      .getAnimations()
      .filter((animation) => {
        const timing = (animation.effect as KeyframeEffect | null)?.getTiming();
        return timing !== undefined && timing.iterations !== Infinity;
      })
      .map((animation) => animation.finished.catch(() => undefined));

    await Promise.race([
      Promise.all(finite),
      new Promise((resolve) => setTimeout(resolve, 2_000)),
    ]);
  });
}

/** The map is either a fully painted basemap or the labelled fallback. */
async function expectMapSettled(page: Page) {
  const googleMap = page.locator('[data-testid="planned-dispatch-map"]');
  if ((await googleMap.count()) === 0) return; // schematic, or a non-map view

  await expect
    .poll(
      async () =>
        (await googleMap.getAttribute("data-map-ready")) === "true" ||
        (await page.locator('[data-testid="dispatch-svg-schematic"]').count()) > 0,
      { timeout: 20_000, message: "map painted, or degraded to the schematic" },
    )
    .toBe(true);

  // The loading surface must be gone before anything is captured.
  await expect(page.locator('[data-testid="map-loading"]')).toHaveCount(0);
}

const cursor = async (page: Page): Promise<number> =>
  Number(await page.locator('[data-testid="app-root"]').getAttribute("data-cursor"));

/**
 * Wait until the cursor stops moving.
 *
 * `pause` stops the autoplay loop, but a frame already in flight can still
 * land immediately after. Tests that measure "this click changed nothing"
 * need a quiet baseline first.
 */
async function settleCursor(page: Page, quietMs = 1_200) {
  let last = await cursor(page);
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(quietMs);
    const now = await cursor(page);
    if (now === last) return now;
    last = now;
  }
  return last;
}

/** Every ordinal currently rendered in the Fleet Activity rail, in order. */
async function railOrdinals(page: Page): Promise<string[]> {
  return await page
    .locator('[data-testid="activity-entry"]')
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-ordinal") ?? ""));
}

/** The runtime's own committed feed — canonical truth, read from the API. */
async function feedOf(page: Page, sid: string): Promise<number[]> {
  const state = await (await page.request.get(`${RUNTIME}/api/v1/replay/sessions/${sid}`)).json();
  return (state.feed ?? []).map((e: { sequence: number }) => e.sequence);
}

/** No canonical event later than `maxSeq` may be rendered in the rail. */
async function expectNoFutureCanonical(page: Page, maxSeq: number) {
  const future = (await railOrdinals(page)).filter(
    (o) => !o.startsWith("b") && Number(o) > maxSeq,
  );
  expect(future, `no canonical event beyond ${maxSeq} may appear`).toEqual([]);
}

/** The rail carries exactly these isolated ordinals, and no others. */
async function expectBranchActivity(page: Page, expected: string[]) {
  const isolated = await page
    .locator('[data-testid="activity-entry"][data-authority="ISOLATED"]')
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-ordinal") ?? ""));
  expect(isolated.sort()).toEqual([...expected].sort());
}

/** Wait until the session cursor reaches at least `target`. */
async function waitForCursor(page: Page, target: number, timeout = 90_000) {
  await expect
    .poll(() => cursor(page), { timeout, message: `cursor >= ${target}` })
    .toBeGreaterThanOrEqual(target);
}

/** Assert no horizontal overflow at the acceptance viewport. */
async function expectNoHorizontalOverflow(page: Page) {
  const { scrollW, clientW } = await page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
  }));
  expect(scrollW, "no horizontal overflow at 1600×900").toBeLessThanOrEqual(clientW);
}

test.describe("Golden journey", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
  });

  test("the runtime is the deterministic Golden Runtime Controller", async ({ request }) => {
    const res = await request.post(`${RUNTIME}/api/v1/replay/sessions`, { data: {} });
    expect(res.status()).toBe(201);
    expect(res.headers()["x-full-shelf-replay-mode"]).toBe("DETERMINISTIC_TEST");
    const body = await res.json();
    // A new session opens at event 5 with Friday already open.
    expect(body.cursor).toBe(5);
    expect(body.synthetic).toBe(true);
  });

  test("events 5→25: approval gate, recall hold, recovery states, proof branches, Saturday", async ({
    page,
  }) => {
    // ---------------------------------------------------------------
    // 1. Opening — event 5. Friday opens, rev07 active.
    // ---------------------------------------------------------------
    // The opening frame must be event 5 deterministically, so the page is
    // loaded PAUSED. Autoplay is then started explicitly below, which is
    // the same normal-product progression an operator sees — this test
    // still exercises the real autoplay, the gate, and the event-11 hold.
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });

    await expect(page.locator('[data-testid="clock"]')).toHaveText("08:05");
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");
    expect(await cursor(page)).toBe(5);

    // The map footer carries the OSM route attribution, and nothing else.
    await expect(page.locator('[data-testid="map-location-disclosure"]')).toContainText(
      "Route geometry © OpenStreetMap contributors",
    );
    // Presenter transport controls must not exist on the film canvas.
    await expect(page.getByRole("button", { name: /^(play|pause|advance|step|next event)$/i })).toHaveCount(0);
    // Saturday is unavailable before event 24.
    await expect(page.locator('[data-testid="day-sat"]')).toHaveAttribute("data-available", "false");
    await expect(page.locator('[data-testid="day-sat"]')).toBeDisabled();

    // Event 5 has no failure yet: the alert belongs to event 6.
    await expect(page.locator('[data-testid="truck-failure-alert"]')).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await shot(page, "01-opening");

    // ---------------------------------------------------------------
    // 2. Event 6 — Truck 1 refrigeration failure, prominent alert.
    // ---------------------------------------------------------------
    await page.request
      .post(`${RUNTIME}/api/v1/replay/sessions/${await sessionIdOf(page)}/start`, {
        data: { interval_ms: 900 },
      })
      .catch(() => {});
    await waitForCursor(page, 6);
    const failure = page.locator('[data-testid="truck-failure-alert"]');
    await expect(failure).toBeVisible({ timeout: 30_000 });
    await expect(failure).toContainText(/REFRIGERATION FAILURE/i);
    await expect(failure).toContainText("TRUCK-01");
    // The incident badge is projection-driven, never view-derived.
    await expect(page.locator('[data-testid="incident-badge"]')).toBeVisible();
    // Truck 1 is never silently repaired: it stays failed for the rest
    // of the day, including after rev08 activates.
    await expect(failure).toBeVisible();

    await expectNoHorizontalOverflow(page);
    await shot(page, "02-truck-failure");

    // ---------------------------------------------------------------
    // 3. Event 8 — structured proposal; the runtime waits for a human.
    // ---------------------------------------------------------------
    const proposal = page.locator('[data-testid="repair-proposal"]');
    await expect(proposal).toBeVisible({ timeout: 60_000 });
    await expect(proposal).toContainText("O202");
    await expect(proposal).toContainText("O203");
    // The Truck 2 arithmetic: 36 + 22 = 58/60.
    await expect(page.locator('[data-testid="proposal-reroute"]')).toContainText("36 + 22 = 58 / 60");

    // The approval action is visible and enabled — the only human gate.
    const approve = page.locator('[data-testid="approve-update"]');
    await expect(approve).toBeVisible();
    await expect(approve).toBeEnabled();

    // The gate genuinely holds: the runtime refuses `advance` at event 8
    // and progression does not slip past it on its own.
    await expect.poll(() => cursor(page), { timeout: 20_000 }).toBe(8);
    const refused = await page.request.post(
      `${RUNTIME}/api/v1/replay/sessions/${await sessionIdOf(page)}/advance`,
    );
    expect(refused.status()).toBe(409);
    expect((await refused.json()).detail).toBe("HUMAN_APPROVAL_REQUIRED");
    // Still rev07: nothing was committed by the refusal.
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");

    await expectNoHorizontalOverflow(page);
    await shot(page, "03-repair-proposal");

    // ---------------------------------------------------------------
    // 4. Event 9 commits the approval; event 10 activates rev08.
    // ---------------------------------------------------------------
    await approve.click();

    // Event 9 arrives first and is a separate commit from event 10.
    await waitForCursor(page, 9, 30_000);
    const rail = page.locator('[data-testid="fleet-activity-rail"]');
    await expect(rail.locator('[data-ordinal="9"]')).toBeVisible({ timeout: 30_000 });

    // Event 10 then activates rev08 — Truck 2 becomes exactly 58/60.
    await waitForCursor(page, 10, 30_000);
    await expect(rail.locator('[data-ordinal="10"]')).toBeVisible();
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev08");

    const manifests = page.locator('[data-testid="truck-manifests"]');
    await expect(manifests).toContainText("58 cases");
    // O203 becomes refrigerated partner fulfilment, not a shortfall, and
    // is named consistently as the configured partner carrier.
    await expect(manifests).toContainText("Partner fulfillment");
    await expect(manifests).toContainText("Tri-City Cold Storage");
    await expect(manifests).toContainText("O203");

    await expectNoHorizontalOverflow(page);
    await shot(page, "04-rev08-active");

    // ---------------------------------------------------------------
    // 5. Event 11 — the recall pauses progression while still on Today.
    // ---------------------------------------------------------------
    const pauseBanner = page.locator('[data-testid="recall-pause-banner"]');
    await expect(pauseBanner).toBeVisible({ timeout: 40_000 });
    await expect(pauseBanner).toContainText(/RECALL NOTICE RECEIVED/i);

    const heldAt = await cursor(page);
    expect(heldAt).toBe(11);
    // The hold is real: the cursor does not move while we stay on Today.
    await page.waitForTimeout(4_000);
    expect(await cursor(page), "progression is paused on Today at event 11").toBe(heldAt);

    await expectNoHorizontalOverflow(page);
    await shot(page, "05-recall-intake");

    // Opening Incidents is how the operator picks the recall up. In a
    // filmed take progression is presenter-driven, so autoplay is
    // restarted here exactly as the product does when the hold clears.
    await page.locator('[data-testid="nav-incident"]').click();
    await page.request
      .post(`${RUNTIME}/api/v1/replay/sessions/${await sessionIdOf(page)}/start`, {
        data: { interval_ms: 900 },
      })
      .catch(() => {});
    await expect
      .poll(() => cursor(page), { timeout: 40_000, message: "progression resumes past the recall" })
      .toBeGreaterThan(heldAt);

    // ---------------------------------------------------------------
    // 6. Event 18 — custody: 96 unique, 88 confirmed, 8 at Site 01.
    // ---------------------------------------------------------------
    await waitForCursor(page, 18);

    // No tab navigation: the workspace advances to custody on its own.
    const custody = page.locator('[data-testid="custody-headline"]');
    await expect(custody).toBeVisible({ timeout: 30_000 });
    await expect(custody).toContainText("96 affected cases traced");
    await expect(custody).toContainText("8 awaiting confirmation");

    const custodyPanel = page.locator("main");
    await expect(custodyPanel).toContainText("East Bay Distribution Annex");
    // 24 + 22 + 20 + 10 + 8 + 12 = 96 — intermediate subtotals not re-added.
    await expect(custodyPanel).toContainText("24 + 22 + 20 + 10 + 8 + 12 = 96");

    await expectNoHorizontalOverflow(page);
    await shot(page, "06-custody");

    // Navigation must not move the cursor. Tabs are NAVIGATION_ONLY.
    const beforeTabs = await cursor(page);
    await page.locator('[data-testid="nav-history"]').click();
    await page.locator('[data-testid="nav-incident"]').click();
    await page.locator('[data-testid="stage-detect"]').click();
    await page.locator('[data-testid="stage-custody"]').click();
    const afterTabs = await cursor(page);
    expect(afterTabs, "stage review never rewinds the cursor").toBeGreaterThanOrEqual(beforeTabs);
  });

  // -----------------------------------------------------------------
  // The recovery, refusal, branch and Saturday assertions run against a
  // session driven to its terminal state, so they are not racing the
  // 900ms autoplay for the narrow event-19 window.
  // -----------------------------------------------------------------
  /**
   * The map surface. With an authorized VITE_GOOGLE_MAPS_API_KEY the
   * Google basemap must genuinely paint tiles; without one the truthful
   * deterministic schematic must stand in its place. Either way the
   * configured-reference disclosure is present and no live GPS, driven
   * route, or moving vehicle is ever claimed.
   */
  test("the map renders configured reference locations without claiming live GPS", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });

    const keyConfigured = await page.evaluate(
      () => !!(import.meta as unknown as { env?: Record<string, string> }).env
        ?.VITE_GOOGLE_MAPS_API_KEY,
    ).catch(() => false);

    const googleMap = page.locator('[data-testid="planned-dispatch-map"]');
    const schematic = page.locator('[data-testid="dispatch-svg-schematic"]');

    // Exactly one map surface renders — never a blank panel, never both.
    await expect
      .poll(async () => (await googleMap.count()) + (await schematic.count()), { timeout: 20_000 })
      .toBe(1);

    if ((await googleMap.count()) === 1) {
      // A key that loads the API but paints nothing must fall back, so a
      // surviving Google surface means tiles genuinely painted.
      await expect(googleMap).toBeVisible();
      const tiles = await page.evaluate(
        () =>
          document.querySelectorAll(
            'img[src*="googleapis.com"], img[src*="gstatic.com"], [data-testid="planned-dispatch-map"] canvas',
          ).length,
      );
      expect(tiles, "Google basemap painted real tiles").toBeGreaterThan(0);
      await expect(page.locator('[data-testid="map-provenance-label"]')).toContainText(
        "Planned routes",
      );
    } else {
      // Truthful fallback: only legitimate when no authorized key painted.
      await expect(schematic).toBeVisible();
      await expect(page.locator('[data-testid="schematic-provenance-label"]')).toContainText(
        "Planned routes",
      );
      console.log(`map fallback rendered (key configured: ${keyConfigured})`);
    }

    // Both paths carry the required OpenStreetMap route attribution.
    await expect(page.locator('[data-testid="map-location-disclosure"]')).toContainText(
      "Route geometry © OpenStreetMap contributors",
    );

    // Nothing may CLAIM a moving truck, a driven route, or a live fix.
    // Negated disclosures ("no positions or bearings", "not live GPS")
    // are exactly what this surface is required to say, so the check
    // targets affirmative claims rather than bare substrings.
    const body = await page.locator("body").innerText();
    const claims = [
      /(?<!no |not )\blive GPS\b(?! or)/i,
      /\ben route\b/i,
      /\bdriven route\b/i,
      /\bcurrent position\b/i,
      /\blast reported\b/i,
      /\bheading\s+\d/i,
      /\bspeed\b\s*[:=]/i,
    ];
    for (const claim of claims) {
      expect(body, `must not affirmatively claim ${claim}`).not.toMatch(claim);
    }

    await expectNoHorizontalOverflow(page);
  });

  test("event 6 shows the refrigeration failure before any proposal exists", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    // Hold at 6 so the alert is captured as event 6 — not as a byproduct
    // of event 8, where the proposal is already on screen.
    await driveTo(page, sid, 6);

    const failure = page.locator('[data-testid="truck-failure-alert"]');
    await expect(failure).toBeVisible({ timeout: 30_000 });
    await expect(failure).toContainText("TRUCK-01");
    await expect(failure).toContainText(/REFRIGERATION FAILURE/i);
    // rev07 is still authoritative and no proposal has been made yet.
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");
    await expect(page.locator('[data-testid="repair-proposal"]')).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await shot(page, "02-truck-failure");
  });

  test("event 19 advisory and event 20 committed recovery are distinct", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    // Hold the session at 19 so the advisory state is genuinely rendered.
    await driveTo(page, sid, 19);
    await page.locator('[data-testid="nav-incident"]').click();

    const proposed = page.locator('[data-testid="recovery-proposed"]');
    await expect(proposed).toBeVisible({ timeout: 30_000 });
    // Advisory: amber, explicitly not committed, zero mutations applied.
    await expect(proposed).toHaveAttribute("data-mutation-applied", "false");
    await expect(page.locator('[data-testid="recovery-status-badge"]')).toContainText(
      /PROPOSED · ADVISORY · NOT COMMITTED/,
    );
    await expect(page.locator('[data-testid="recovery-advisory-note"]')).toContainText(
      /No domain mutation has been applied/i,
    );
    await expect(page.locator('[data-testid="recovery-proposed-total"]')).toContainText("40");
    await expect(page.locator('[data-testid="recovery-proposed-shortfall"]')).toContainText("20");
    await expect(page.locator('[data-testid="recovery-proposed-shortfall"]')).toContainText("AGENCY-03");
    // The committed panel must NOT exist yet.
    await expect(page.locator('[data-testid="recovery-committed"]')).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await shot(page, "07-recovery-proposed");

    // Event 20 commits it. Green, committed, still truthfully 20 short.
    await driveTo(page, sid, 20);
    const committed = page.locator('[data-testid="recovery-committed"]');
    await expect(committed).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('[data-testid="recovery-status-badge"]')).toContainText(
      /COMMITTED · ALLOCATED FROM SAFE STOCK/,
    );
    // The advisory panel is replaced, not relabelled.
    await expect(page.locator('[data-testid="recovery-proposed"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="recovery-committed-total"]')).toContainText("40");
    await expect(page.locator('[data-testid="recovery-committed-shortfall"]')).toContainText("20");
    await expect(page.locator('[data-testid="recovery-committed-shortfall"]')).toContainText("AGENCY-03");

    // Event 21 commits the closure refusal; the runtime first exposes it
    // on the projection at cursor 22, together with PARTIALLY_CONTAINED.
    // The refusal itself applied ZERO domain mutations.
    await driveTo(page, sid, 22);
    await expect(page.locator('[data-testid="incident-status"]')).toHaveText("PARTIALLY_CONTAINED", {
      timeout: 30_000,
    });

    const refusal = page.locator("main");
    await expect(refusal).toContainText(/CLOSURE BLOCKED/i, { timeout: 30_000 });
    await expect(refusal).toContainText(/DENIED/i);
    // Zero mutations, stated on the surface an operator reads.
    await expect(refusal).toContainText(/0\s*MUTATIONS/i);
    // Refusal is not fabricated completion: the shortfall is still open.
    await expect(refusal).toContainText("20");

    await expectNoHorizontalOverflow(page);
    await shot(page, "08-recovery-committed-refusal");
  });

  test("evidence branches run in isolation and restore canonical state", async ({ page }) => {
    // Proof controls are DEBUG-ONLY, so isolation is proven in debug mode.
    await page.goto("/?debug=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    // Branches are refused before event 22 — assert the runtime's refusal.
    await driveTo(page, sid, 21);
    const early = await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/branch`, {
      data: { proof: "vague" },
    });
    expect(early.status()).toBe(409);
    expect((await early.json()).detail).toBe("PROOF_BRANCH_NOT_AVAILABLE_YET");

    await driveTo(page, sid, 22);
    await page.locator('[data-testid="nav-incident"]').click();

    const panel = page.locator('[data-testid="evidence-branch-panel"]');
    await expect(panel).toBeVisible({ timeout: 30_000 });
    await expect(panel).toHaveAttribute("data-branch", "canonical");
    // Canonical custody before any branch: 88 of 96.
    await expect(page.locator('[data-testid="branch-custody-figure"]')).toHaveText("88/96");

    // The canonical baseline every isolation claim below is measured against.
    const cursorAt22 = await cursor(page);
    expect(cursorAt22).toBe(22);
    const canonicalOrdinals = await railOrdinals(page);
    const canonicalFeed = await feedOf(page, sid);

    // ---- vague branch: denied, 0 domain / 1 evidence mutation --------
    await page.locator('[data-testid="branch-enter-vague"]').click();
    await expect(panel).toHaveAttribute("data-branch", "vague", { timeout: 30_000 });
    await expect(page.locator('[data-testid="header-branch-label"]')).toContainText(
      "ISOLATED SELECTED PROOF",
    );
    const vagueResult = page.locator('[data-testid="branch-evidence-result"]');
    await expect(vagueResult).toHaveAttribute("data-decision", "DENIED");
    await expect(page.locator('[data-testid="branch-decision"]')).toContainText("DENIED");
    const vagueMut = page.locator('[data-testid="branch-mutations"]');
    await expect(vagueMut).toHaveAttribute("data-domain-mutations", "0");
    await expect(vagueMut).toHaveAttribute("data-evidence-mutations", "1");
    // Custody is untouched by a denial.
    await expect(page.locator('[data-testid="branch-custody-figure"]')).toHaveText("88/96");

    // Entering a proof must not advance the canonical cursor, and canonical
    // progression must be held: events 23-25 may not commit while open.
    expect(await cursor(page), "vague branch did not advance the cursor").toBe(cursorAt22);
    await page.waitForTimeout(3_000); // longer than several autoplay ticks
    expect(await cursor(page), "canonical progression is paused in-branch").toBe(cursorAt22);
    await expectNoFutureCanonical(page, 22);

    // The vague proof's own entries are present and marked isolated.
    await expectBranchActivity(page, ["b1", "b2", "b3", "b4"]);
    await expect(
      page.locator('[data-testid="activity-entry"][data-authority="ISOLATED"]'),
      "vague branch shows exactly its own four isolated entries",
    ).toHaveCount(4);
    await expect(page.locator('[data-testid="fleet-activity-rail"]')).toContainText(
      "Partner evidence denied",
    );

    await expectNoHorizontalOverflow(page);
    await shot(page, "09-vague-evidence");

    // Exit restores canonical exactly: cursor, rail, feed, custody.
    await page.locator('[data-testid="branch-exit"]').click();
    await expect(panel).toHaveAttribute("data-branch", "canonical", { timeout: 30_000 });
    await expect(page.locator('[data-testid="branch-custody-figure"]')).toHaveText("88/96");
    await expect(
      page.locator('[data-testid="activity-entry"][data-authority="ISOLATED"]'),
      "exiting removes every isolated entry",
    ).toHaveCount(0);
    await expect(page.locator('[data-testid="fleet-activity-rail"]')).not.toContainText(
      "Partner evidence denied",
    );

    // ---- complete branch: isolated 96/96 ----------------------------
    await page.locator('[data-testid="branch-enter-complete"]').click();
    await expect(panel).toHaveAttribute("data-branch", "complete", { timeout: 30_000 });
    const completeResult = page.locator('[data-testid="branch-evidence-result"]');
    await expect(completeResult).toHaveAttribute("data-decision", "APPLIED");
    // The isolated proof reaches 96/96 — and only in isolation.
    await expect(page.locator('[data-testid="branch-custody-figure"]')).toHaveText("96/96");
    const completeMut = page.locator('[data-testid="branch-mutations"]');
    await expect(completeMut).toHaveAttribute("data-domain-mutations", "2");
    await expect(completeMut).toHaveAttribute("data-evidence-mutations", "1");
    await expect(page.locator('[data-testid="branch-authority-label"]')).toContainText(
      "ISOLATED SELECTED PROOF",
    );

    expect(await cursor(page), "complete branch did not advance the cursor").toBe(cursorAt22);
    await page.waitForTimeout(3_000);
    expect(await cursor(page), "canonical progression is paused in-branch").toBe(cursorAt22);
    await expectNoFutureCanonical(page, 22);

    // The vague proof's result must NOT be visible inside the complete
    // proof. This is the exact cross-branch leak the audit caught.
    await expect(
      page.locator('[data-testid="activity-entry"][data-authority="ISOLATED"]'),
      "complete branch shows exactly its own four isolated entries",
    ).toHaveCount(4);
    await expect(
      page.locator('[data-testid="fleet-activity-rail"]'),
      "vague-branch activity must never appear in the complete branch",
    ).not.toContainText("Partner evidence denied");
    await expect(page.locator('[data-testid="fleet-activity-rail"]')).toContainText(
      "Partner evidence applied",
    );

    await expectNoHorizontalOverflow(page);
    await shot(page, "10-complete-evidence");

    // A branch that resolves the cases must not simultaneously headline
    // the canonical "8 cases remain unconfirmed" refusal.
    await page.locator('[data-testid="stage-closure"]').click();
    await expect(page.locator('[data-testid="branch-resolved-closure"]')).toBeVisible();
    await expect(page.locator("main")).not.toContainText(
      "Closure refused — 8 cases remain unconfirmed",
    );

    // ---- exit restores canonical 88/96 and PARTIALLY_CONTAINED ------
    await page.locator('[data-testid="branch-exit"]').click();
    await expect(panel).toHaveAttribute("data-branch", "canonical", { timeout: 30_000 });
    await expect(page.locator('[data-testid="branch-custody-figure"]')).toHaveText("88/96");
    await expect(page.locator('[data-testid="header-branch-label"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="incident-status"]')).toHaveText("PARTIALLY_CONTAINED");
    await expect(
      page.locator('[data-testid="activity-entry"][data-authority="ISOLATED"]'),
    ).toHaveCount(0);

    // The custody surface itself agrees: canonical is back to 88 of 96.
    await page.locator('[data-testid="stage-custody"]').click();
    await expect(page.locator('[data-testid="custody-headline"]')).toContainText(
      "96 affected cases traced",
    );
    await expect(page.locator("main")).toContainText("8 awaiting confirmation");

    await expectNoHorizontalOverflow(page);
    await shot(page, "11-canonical-return");

    // Capture the canonical-return frame BEFORE progression resumes, then
    // prove the runtime's own feed and the rail came back unchanged.
    expect(await feedOf(page, sid), "canonical feed restored exactly").toEqual(canonicalFeed);
    const restoredOrdinals = (await railOrdinals(page)).filter((o) => !o.startsWith("b"));
    expect(restoredOrdinals, "canonical rail restored exactly").toEqual(canonicalOrdinals);

    // Only after returning to canonical may progression resume through 23-25.
    // Event 24 is a deliberate indefinite hold (the Saturday draft is meant
    // to be reviewed, not raced past), so the last step is driven.
    await waitForCursor(page, 24, 60_000);
    await driveTo(page, sid, 25);
    await expect(page.locator('[data-testid="fleet-activity-rail"]')).toContainText(
      "Obligations carried forward",
    );
  });

  test("Saturday is unavailable before event 24 and available after", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    // Event 23: still no next-day draft.
    await driveTo(page, sid, 23);
    const sat = page.locator('[data-testid="day-sat"]');
    await expect(sat).toHaveAttribute("data-available", "false", { timeout: 30_000 });
    await expect(sat).toBeDisabled();

    // Event 24: the Saturday draft becomes available.
    await driveTo(page, sid, 24);
    await expect(sat).toHaveAttribute("data-available", "true", { timeout: 30_000 });
    await expect(sat).toBeEnabled();

    await sat.click();
    const main = page.locator("main");
    await expect(main).toContainText("DRAFT_WITH_CONSTRAINTS", { timeout: 30_000 });
    // A draft is never activatable.
    await expect(page.getByRole("button", { name: /^activate/i })).toHaveCount(0);

    // Event 25 — four obligations carried forward.
    await driveTo(page, sid, 25);
    for (const ref of ["BARRIER-4471", "SF-A03", "WORK-SITE01", "INC-2231"]) {
      await expect(main, `obligation ${ref} carried forward`).toContainText(ref);
    }

    await expectNoHorizontalOverflow(page);
    await shot(page, "12-saturday-draft");
  });

  // ===================================================================
  // Material assertions.
  //
  // These restore coverage that the superseded beat-stepped suite held,
  // rebuilt on the session runtime. No beat navigation is used, and no UI
  // claim is replaced by a direct API assertion: where the runtime is
  // called it is to CAUSE a condition, never to stand in for the check.
  // ===================================================================

  test("reviewing completed stages preserves exact cursor equality", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 22);

    // Enter Incidents FIRST. Opening Incidents legitimately releases the
    // event-11 hold and resumes autoplay, so the runtime is quieted after
    // that navigation — otherwise this test would be measuring resumed
    // progression rather than the tab clicks it is about.
    await page.locator('[data-testid="nav-incident"]').click();
    await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/pause`).catch(() => {});
    await settleCursor(page);

    const before = await cursor(page);
    const clockBefore = await page.locator('[data-testid="clock"]').textContent();

    for (const stage of ["detect", "scope", "custody", "recover", "closure", "custody", "detect"]) {
      await page.locator(`[data-testid="stage-${stage}"]`).click();
      expect(await cursor(page), `stage ${stage} is NAVIGATION_ONLY`).toBe(before);
    }
    // Returning to the live stage is navigation too.
    await page.locator('[data-testid="stage-unpin"]').click();
    expect(await cursor(page), "unpinning is NAVIGATION_ONLY").toBe(before);
    // Left-nav view changes are navigation too. History and back is a
    // pure view change; Today -> Incidents is deliberately excluded here
    // because that transition legitimately releases the event-11 hold.
    await page.locator('[data-testid="nav-history"]').click();
    expect(await cursor(page), "History is NAVIGATION_ONLY").toBe(before);
    await page.locator('[data-testid="nav-incident"]').click();

    const after = await cursor(page);
    expect(after, "after === before").toBe(before);
    await expect(page.locator('[data-testid="clock"]')).toHaveText(clockBefore ?? "");
  });

  test("an altered or missing approval binding is refused and changes nothing", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 8);
    await expect(page.locator('[data-testid="approve-update"]')).toBeVisible({ timeout: 30_000 });

    const template = (
      await (await page.request.get(`${RUNTIME}/api/v1/replay/sessions/${sid}/projection`)).json()
    ).current_day.repair_proposal.approval_payload_template;

    const cursorBefore = await cursor(page);

    // Missing plan_diff_hash.
    const { plan_diff_hash: _omitted, ...missing } = template;
    const r1 = await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/approve`, {
      data: { ...missing, idempotency_key: "test-missing" },
    });
    expect(r1.status()).toBe(409);
    expect((await r1.json()).detail).toBe("APPROVAL_BINDING_MISMATCH");

    // Altered bound value — the case count no longer matches the diff.
    const altered = JSON.parse(JSON.stringify(template));
    altered.actions[0].cases = 21;
    const r2 = await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/approve`, {
      data: { ...altered, idempotency_key: "test-altered" },
    });
    expect(r2.status()).toBe(409);
    expect((await r2.json()).detail).toBe("APPROVAL_BINDING_MISMATCH");

    // Zero mutations: the UI still shows rev07, still at event 8, still
    // offering the same approval.
    expect(await cursor(page)).toBe(cursorBefore);
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");
    await expect(page.locator('[data-testid="approve-update"]')).toBeVisible();
    await expectNoFutureCanonical(page, 8);
  });

  test("the approval control disappears once the update is committed", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 8);
    await expect(page.locator('[data-testid="approve-update"]')).toBeVisible({ timeout: 30_000 });

    await driveTo(page, sid, 10); // driveTo approves through the real control
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev08");

    // No approval affordance survives commitment, anywhere on the page.
    await expect(page.locator('[data-testid="approve-update"]')).toHaveCount(0);
    await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
  });

  test("the approval action stays in the side rail and above fold at 1600x900", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 8);
    const approve = page.locator('[data-testid="approve-update"]');
    await expect(approve).toBeVisible({ timeout: 30_000 });

    // Exactly one approval control exists — never duplicated.
    await expect(approve).toHaveCount(1);

    // It lives inside the Fleet Activity side rail (the locked UX
    // decision), not in the main workspace.
    const inSideRail = await approve.evaluate(
      (el) => !!el.closest("aside") && !el.closest("main"),
    );
    expect(inSideRail, "approval stays in the side rail, not the workspace").toBe(true);

    // Above fold at the acceptance viewport.
    const box = await approve.boundingBox();
    expect(box, "approval control has a box").not.toBeNull();
    expect(box!.y, "approval top is on-screen").toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height, "approval is fully above fold at 900px").toBeLessThanOrEqual(900);

    await expectNoHorizontalOverflow(page);
  });

  test("no future canonical state leaks before its event", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    // At event 5 nothing later may be visible anywhere on the page.
    await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/pause`).catch(() => {});
    await expect(page.locator('[data-testid="clock"]')).toHaveText("08:05");
    expect(await cursor(page), "still at the opening event").toBe(5);
    let body = await page.locator("body").innerText();
    for (const later of [
      "rev08",                    // event 10
      "LTC-4471 barrier",         // event 25
      "PARTIALLY_CONTAINED",      // event 22
      "DRAFT_WITH_CONSTRAINTS",   // event 24
      "96 cases traced",          // event 18
    ]) {
      expect(body, `"${later}" must not appear at event 5`).not.toContain(later);
    }
    await expectNoFutureCanonical(page, 5);

    // At event 18 custody exists, but recovery and Saturday do not.
    await driveTo(page, sid, 18);
    await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/pause`).catch(() => {});
    const settled = await settleCursor(page);
    await page.locator('[data-testid="nav-incident"]').click();
    await expect(page.locator('[data-testid="recovery-committed"]')).toHaveCount(0);

    // The Saturday toggle lives on Today, so check it there.
    await page.locator('[data-testid="nav-today"]').click();
    await expect(page.locator('[data-testid="day-sat"]')).toHaveAttribute("data-available", "false");
    await expect(page.locator('[data-testid="day-sat"]')).toBeDisabled();
    body = await page.locator("body").innerText();
    expect(body, "the Saturday draft must not leak at event 18").not.toContain(
      "DRAFT_WITH_CONSTRAINTS",
    );
    await expectNoFutureCanonical(page, settled);
  });

  test("no agent RUNNING / WAITING / duration state appears anywhere", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    // Sweep the whole journey, including the drawer and both branches —
    // the runtime emits no such field, so none may ever be rendered.
    await driveTo(page, sid, 22);
    await page.locator('[data-testid="open-execution-record"]').click();
    await expect(page.locator('[data-testid="execution-record-drawer"]')).toBeVisible();

    const body = await page.locator("body").innerText();
    for (const invented of [
      /\bRUNNING\b/,
      /\bWAITING\b/,
      /\bIN[_ ]PROGRESS\b(?!.*CONTAINMENT)/,
      /\b\d+\s*ms\b/,
      /\belapsed\b/i,
      /\btook\s+\d/i,
    ]) {
      expect(body, `invented agent lifecycle ${invented} must not appear`).not.toMatch(invented);
    }
  });

  test("film mode hides debug controls but keeps the product approval action", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 8);
    // The product's own human gate is present…
    await expect(page.locator('[data-testid="approve-update"]')).toBeVisible({ timeout: 30_000 });

    // …while presenter/debug transport is absent from the film canvas.
    await expect(
      page.getByRole("button", { name: /^(play|pause|resume|advance|step|next event|reset|replay)$/i }),
    ).toHaveCount(0);
    await expect(page.locator("[data-testid^='beat-'], [data-testid^='moment-']")).toHaveCount(0);
    await expect(page.locator("[data-testid='replay-controls']")).toHaveCount(0);
    await expect(page.locator("[data-testid='debug-advance']")).toHaveCount(0);
    await expect(page.locator("[data-testid='debug-cursor']")).toHaveCount(0);
    // Proof selection must not exist outside debug mode.
    await expect(page.locator('[data-testid="branch-enter-vague"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="branch-enter-complete"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="branch-exit"]')).toHaveCount(0);
    await expect(page.getByRole("button", { name: /vague evidence|complete evidence|return to canonical/i })).toHaveCount(0);
  });

  test("a missing Maps key produces the truthful schematic fallback", async ({ page }) => {
    // Forced so this path is genuinely exercised even on a machine that
    // has a key configured.
    await page.addInitScript(() => {
      (globalThis as { __FS_FORCE_NO_MAP_KEY?: boolean }).__FS_FORCE_NO_MAP_KEY = true;
    });

    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });

    // No Google surface, no blank panel — the labelled schematic instead.
    await expect(page.locator('[data-testid="planned-dispatch-map"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="dispatch-svg-schematic"]')).toBeVisible();
    await expect(page.locator('[data-testid="map-mode-label"]')).toContainText("Planned routes");
    await expect(page.locator('[data-testid="map-location-disclosure"]')).toContainText(
      "Route geometry © OpenStreetMap contributors",
    );
    // A fallback must never leave a loading surface stranded on screen.
    await expect(page.locator('[data-testid="map-loading"]')).toHaveCount(0);

    // The key must never be exposed on the page when it is not in use.
    expect(await page.content()).not.toMatch(/AIza[0-9A-Za-z_-]{20,}/);

    await expectNoHorizontalOverflow(page);
  });

  test("a Maps API load failure degrades to the truthful schematic", async ({ page }) => {
    // Fail the real loader at the network boundary — not by stubbing our
    // own code — so the component's actual failure path runs.
    await page.route("https://maps.googleapis.com/**", (route) => route.abort());

    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });

    await expect(page.locator('[data-testid="dispatch-svg-schematic"]')).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator('[data-testid="planned-dispatch-map"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="map-mode-label"]')).toContainText("Planned routes");
    // Bounded: it degraded rather than hanging behind a spinner.
    await expect(page.locator('[data-testid="map-loading"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="map-location-disclosure"]')).toContainText(
      "Route geometry © OpenStreetMap contributors",
    );

    await expectNoHorizontalOverflow(page);
  });

  test("History is read-only and opening the Execution Record does not advance time", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 22);
    await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/pause`).catch(() => {});
    await settleCursor(page);

    // ---- History: provenance only, no mutation affordance ------------
    await page.locator('[data-testid="nav-history"]').click();
    const history = page.locator('[data-testid="history-ledger"]');
    await expect(history).toBeVisible({ timeout: 30_000 });
    await expect(history).toContainText("READ-ONLY");
    // No control that could mutate authoritative state.
    await expect(
      history.getByRole("button", { name: /approve|activate|commit|apply|edit|delete/i }),
    ).toHaveCount(0);
    await expect(history.locator("input, textarea, select")).toHaveCount(0);

    // ---- Execution Record: opens without moving the cursor -----------
    const before = await cursor(page);
    const clockBefore = await page.locator('[data-testid="clock"]').textContent();

    await page.locator('[data-testid="open-execution-record"]').click();
    const drawer = page.locator('[data-testid="execution-record-drawer"]');
    await expect(drawer).toBeVisible();

    expect(await cursor(page), "opening the record is navigation, not an event").toBe(before);
    await expect(page.locator('[data-testid="clock"]')).toHaveText(clockBefore ?? "");
    // Evidence surfaces carry no mutation-styled control.
    await expect(drawer.getByRole("button", { name: /approve|activate|commit/i })).toHaveCount(0);
  });

  // ===================================================================
  // v8 restructuring — presenter mode, route semantics, incident
  // progression, agent truth, Saturday discovery.
  // ===================================================================

  test("presenter mode starts paused and shows no transport controls", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });

    // Starts PAUSED at the opening event and stays there on its own.
    expect(await cursor(page), "presenter opens at event 5").toBe(5);
    await page.waitForTimeout(4_000);
    expect(await cursor(page), "presenter mode does not autoplay").toBe(5);

    // The filmed frame carries NO transport of any kind.
    for (const id of ["replay-controls", "debug-advance", "debug-play", "debug-reset", "debug-cursor"]) {
      await expect(page.locator(`[data-testid="${id}"]`), `${id} must not render`).toHaveCount(0);
    }
    await expect(
      page.getByRole("button", { name: /^(play|pause|resume|advance|step|next event|reset|replay)$/i }),
    ).toHaveCount(0);
    await expect(page.locator("input[type='range']"), "no speed slider").toHaveCount(0);
    await expect(page.locator('[data-testid="branch-enter-vague"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="branch-enter-complete"]')).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
  });

  test("ArrowRight advances exactly one canonical event in presenter mode", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const before = await cursor(page);

    await page.keyboard.press("ArrowRight");
    await expect.poll(() => cursor(page), { timeout: 20_000 }).toBe(before + 1);

    // Exactly one: it does not run on.
    await page.waitForTimeout(3_000);
    expect(await cursor(page), "one keypress commits exactly one event").toBe(before + 1);
  });

  test("no keyboard action bypasses the human approval gate", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });

    // Walk to the gate with the keyboard alone.
    for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
    await expect.poll(() => cursor(page), { timeout: 30_000 }).toBe(8);

    // Hammer every shortcut. None may commit event 9.
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press("ArrowRight");
      await page.keyboard.press("Space");
    }
    await page.waitForTimeout(3_000);
    expect(await cursor(page), "the gate holds against the keyboard").toBe(8);
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");

    // Only the visible human action moves it.
    await page.locator('[data-testid="approve-update"]').click();
    await expect.poll(() => cursor(page), { timeout: 30_000 }).toBeGreaterThanOrEqual(9);
  });

  test("opening Incidents does not resume progression in presenter mode", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 12);
    await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/pause`).catch(() => {});
    const held = await settleCursor(page);

    await page.locator('[data-testid="nav-incident"]').click();
    await page.waitForTimeout(4_000);
    expect(await cursor(page), "navigation alone never resumes a filmed take").toBe(held);
  });

  test("Friday routes carry distinct truck identities and return to the hub", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/pause`).catch(() => {});

    // Truck 1 and Truck 2 are legended as separate identities, and the
    // partner colour is never reused for Truck 1.
    await expect(page.locator('[data-testid="map-legend-truck_1"]')).toBeVisible({ timeout: 20_000 });
    await expect(page.locator('[data-testid="map-legend-truck_2"]')).toBeVisible();

    // Every committed leg begins and ends at the hub.
    const closed = await page.evaluate(async () => {
      const mod = await import("/src/data/contract/routeGeometry.ts");
      const keys = ["T1_REV07", "T2_REV07", "T2_REV08", "PARTNER_REV08", "T2_SATURDAY"];
      return keys.map((k) => {
        const path = mod.routePath(k);
        const [a, b] = [path[0], path[path.length - 1]];
        return { k, n: path.length, closed: a[0] === b[0] && a[1] === b[1] };
      });
    });
    for (const r of closed) {
      expect(r.n, `${r.k} has road geometry`).toBeGreaterThan(20);
      expect(r.closed, `${r.k} returns to the hub`).toBe(true);
    }

    // Truck 1 and partner fulfilment must not share a colour.
    const colors = await page.evaluate(async () => {
      const mod = await import("/src/data/contract/routeGeometry.ts");
      return mod.ROUTE_COLORS;
    });
    expect(colors.TRUCK_1).not.toBe(colors.PARTNER);
    expect(colors.TRUCK_1).not.toBe(colors.TRUCK_2);
    expect(colors.PARTNER).not.toBe(colors.TRUCK_2);
  });

  test("rev08 visibly changes the map and the manifests", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    // Before: Truck 1 holds O202 and O203, and they read as impacted.
    await driveTo(page, sid, 7);
    const manifests = page.locator('[data-testid="truck-manifests"]');
    await expect(manifests).toContainText("O202", { timeout: 30_000 });
    await expect(manifests).toContainText("O203");
    await expect(manifests, "the failure names both affected orders").toContainText(/impacted/i);
    await expect(page.locator('[data-testid="map-legend-unavailable"]')).toBeVisible();

    // After: Truck 2 absorbs O202 and East Oakland becomes partner work.
    await driveTo(page, sid, 10);
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev08", { timeout: 30_000 });
    await expect(manifests).toContainText("58 cases");
    await expect(manifests).toContainText("Partner fulfillment");
    await expect(manifests).toContainText("Tri-City Cold Storage");
    // The partner leg is legended separately from Truck 2.
    await expect(page.locator('[data-testid="map-legend-partner"]')).toBeVisible();
    // Truck 1 stays visible as unavailable rather than disappearing.
    await expect(page.locator("main")).toContainText(/truck 1/i);

    await expectNoHorizontalOverflow(page);
  });

  test("the resolved truck alarm clears the page-level alert", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 6);
    await expect(page.locator('[data-testid="truck-failure-alert"]')).toBeVisible({ timeout: 30_000 });

    // Once rev08 is committed the incident is resolved: the page-level
    // red banner goes, while Truck 1 remains truthfully unavailable.
    await driveTo(page, sid, 10);
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev08", { timeout: 30_000 });
    await expect(page.locator('[data-testid="truck-failure-alert"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="truck-manifests"]')).toContainText(/truck 1/i);
  });

  test("Fleet Activity is newest-first and readable at 1600x900", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    await driveTo(page, sid, 12);
    await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/pause`).catch(() => {});
    await settleCursor(page);

    // Newest committed event is first in the DOM and marked current.
    const ordinals = (await railOrdinals(page)).filter((o) => !o.startsWith("b")).map(Number);
    expect(ordinals.length).toBeGreaterThan(2);
    const descending = [...ordinals].sort((a, b) => b - a);
    expect(ordinals, "rail is newest-first").toEqual(descending);
    await expect(
      page.locator('[data-testid="activity-entry"]').first(),
    ).toHaveAttribute("data-current", "true");

    // The newest card is visible without scrolling the rail.
    const first = page.locator('[data-testid="activity-entry"]').first();
    const box = await first.boundingBox();
    expect(box!.y, "newest entry is on-screen").toBeGreaterThanOrEqual(0);
    expect(box!.y, "newest entry is above the fold").toBeLessThan(900);

    // Body text is legible on film: ~14px or larger for the current card.
    const detailSize = await first.evaluate((el) => {
      const d = el.querySelectorAll("div");
      return parseFloat(getComputedStyle(d[d.length - 2] ?? d[0]).fontSize);
    });
    expect(detailSize, "rail body text is filmable").toBeGreaterThanOrEqual(13);

    // Each event offers a receipt into the Execution Record.
    await first.locator('[data-testid="activity-view-receipt"]').click();
    await expect(page.locator('[data-testid="execution-record-drawer"]')).toBeVisible();
  });

  test("incident stages advance without tab navigation and agents follow events", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    // The tabs are gone entirely.
    for (const tab of ["intake", "custody", "recovery", "evidence"]) {
      await expect(page.locator(`[data-testid="incident-tab-${tab}"]`)).toHaveCount(0);
    }

    await driveTo(page, sid, 13);
    await page.locator('[data-testid="nav-incident"]').click();
    const workspace = page.locator('[data-testid="incident-workspace"]');
    await expect(workspace).toBeVisible({ timeout: 30_000 });

    // Later stages are visibly pending, not populated.
    await expect(page.locator('[data-testid="stage-custody"]')).toHaveAttribute("data-state", "pending");
    await expect(page.locator('[data-testid="stage-custody-summary"]')).toHaveText("pending");
    await expect(page.locator('[data-testid="stage-recover"]')).toHaveAttribute("data-reached", "false");

    // Custody arrives on its own at event 18 — no tab, no click.
    await driveTo(page, sid, 18);
    await expect(workspace).toHaveAttribute("data-live-stage", "custody", { timeout: 30_000 });
    await expect(page.locator('[data-testid="custody-network"]')).toBeVisible();
    // The responsible agent is highlighted with it.
    await expect(page.locator('[data-testid="agent-network-custody"]')).toHaveAttribute(
      "data-agent-state",
      "current",
    );
    // Completed stages keep a one-line summary rather than emptying.
    await expect(page.locator('[data-testid="stage-detect"]')).toHaveAttribute("data-state", "done");
    await expect(page.locator('[data-testid="stage-detect-summary"]')).not.toHaveText("pending");

    // At closure the Incident Lead reads as a recorded refusal.
    await driveTo(page, sid, 22);
    await expect(page.locator('[data-testid="agent-incident-lead"]')).toHaveAttribute(
      "data-agent-state",
      "refused",
      { timeout: 30_000 },
    );
    await expect(page.locator('[data-testid="agent-incident-lead"]')).toContainText("REFUSED BY POLICY");
    // "WORKING NOW" is never shown.
    expect(await page.locator("body").innerText()).not.toMatch(/WORKING NOW/i);

    await expectNoHorizontalOverflow(page);
  });

  test("custody 96/88/8 is visible and unclipped above the fold", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 18);
    await page.locator('[data-testid="nav-incident"]').click();

    await expect(page.locator('[data-testid="custody-traced"]')).toHaveText("96", { timeout: 30_000 });
    await expect(page.locator('[data-testid="custody-confirmed"]')).toHaveText("88");
    await expect(page.locator('[data-testid="custody-unconfirmed"]')).toHaveText("8");

    // The whole result is inside the 900px fold, not clipped.
    const net = page.locator('[data-testid="custody-network"]');
    const box = await net.boundingBox();
    expect(box!.y, "custody starts on-screen").toBeGreaterThanOrEqual(0);
    const headline = await page.locator('[data-testid="custody-headline"]').boundingBox();
    expect(headline!.y + headline!.height, "the 96/88/8 headline is above fold").toBeLessThanOrEqual(900);

    // The eight unconfirmed cases are named at their site.
    await expect(net).toContainText("East Bay Distribution Annex");
    await expectNoHorizontalOverflow(page);
  });

  test("events 19, 20, 21 and 22 are materially distinct", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    // 19 — proposed, nothing committed.
    await driveTo(page, sid, 19);
    await page.locator('[data-testid="nav-incident"]').click();
    await expect(page.locator('[data-testid="recovery-proposed"]')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('[data-testid="recovery-proposed"]')).toHaveAttribute(
      "data-mutation-applied",
      "false",
    );
    await expect(page.locator('[data-testid="recovery-committed"]')).toHaveCount(0);

    // 20 — committed, and the shortfall is still truthfully 20.
    await driveTo(page, sid, 20);
    await expect(page.locator('[data-testid="recovery-committed"]')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('[data-testid="recovery-proposed"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="recovery-committed-shortfall"]')).toContainText("20");

    // 21/22 — closure refused, and the terminal state is amber, not red.
    await driveTo(page, sid, 22);
    await expect(page.locator('[data-testid="incident-status"]')).toHaveText("PARTIALLY_CONTAINED", {
      timeout: 30_000,
    });
    const main = page.locator("main");
    // The refusal is the headline; zero mutations only supports it.
    await expect(main).toContainText("Closure refused — 8 cases remain unconfirmed");
    await expect(main).toContainText(/0\s*MUTATIONS/i);
    // Places are named, never shown as bare identifiers.
    await expect(main).not.toContainText(/\bSite 01\b/);
    await expect(main).not.toContainText(/\bAgency 0\d\b/);
    // Unresolved work stays prominent at the terminal state.
    await expect(page.locator('[data-testid="work-to-do"]')).toBeVisible();
    const items = await page.locator('[data-testid="work-item"]').allInnerTexts();
    expect(items.join(" ")).toContain("East Bay Distribution Annex");
    expect(items.join(" ")).toMatch(/movement barrier/i);
    expect(items.join(" ")).toMatch(/shortfall/i);
    expect(items.join(" ")).toMatch(/before closure/i);
  });

  test("Saturday is discoverable, uses the real map, and never routes Truck 1", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    await driveTo(page, sid, 24);
    // Discovery: the operator is told the draft is ready.
    const cta = page.locator('[data-testid="saturday-ready-cta"]');
    await expect(cta).toBeVisible({ timeout: 30_000 });
    await expect(cta).toContainText("Saturday draft ready");
    await cta.click();

    // One map surface: the real basemap, or the truthful fallback.
    await expect
      .poll(
        async () =>
          (await page.locator('[data-testid="planned-dispatch-map"]').count()) +
          (await page.locator('[data-testid="dispatch-svg-schematic"]').count()),
        { timeout: 20_000 },
      )
      .toBe(1);

    await expect(page.locator('[data-testid="saturday-primary-message"]')).toContainText(
      "40 cases assigned",
    );
    await expect(page.locator('[data-testid="saturday-primary-message"]')).toContainText(
      "20 cases still unassigned",
    );

    // Fleet availability, with no invented return time for Truck 1.
    await expect(page.locator('[data-testid="fleet-truck-1"]')).toContainText("unavailable");
    await expect(page.locator('[data-testid="fleet-truck-1"]')).toContainText(
      "Return time not confirmed",
    );
    await expect(page.locator('[data-testid="fleet-truck-2"]')).toContainText("60-case capacity");

    // The event-11 hold banner must not still be on screen at Saturday.
    await expect(page.locator('[data-testid="recall-pause-banner"]')).toHaveCount(0);
    // Carry-forwards name their facilities.
    await expect(page.locator("main")).not.toContainText(/\bAgency 0\d\b/);
    await expect(page.locator("main")).not.toContainText(/\bSite 01\b/);

    // East Oakland is visible as demand and is NOT on the route.
    const demand = page.locator('[data-testid="unassigned-demand"]');
    await expect(demand).toContainText("East Oakland Community Pantry");
    await expect(demand).toContainText("20");
    const stops = await page.locator('[data-testid="saturday-candidate-stop"]').allInnerTexts();
    expect(stops.join(" "), "East Oakland is not a routed stop").not.toContain("East Oakland");

    // Truck 1 is never routed on Saturday.
    const t1Routed = await page.evaluate(async () => {
      const mod = await import("/src/data/contract/routeGeometry.ts");
      return mod.saturdayRoute().role;
    });
    expect(t1Routed, "Saturday routes Truck 2 only").toBe("TRUCK_2");

    await expectNoHorizontalOverflow(page);
  });

  test("day totals partition 96 cases into delivered and remaining", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    const totals = async () => ({
      total: Number((await page.locator('[data-testid="total-cases"]').innerText()).replace(/\D+/g, "")),
      delivered: Number((await page.locator('[data-testid="delivered-cases"]').innerText()).replace(/\D+/g, "")),
      remaining: Number((await page.locator('[data-testid="remaining-cases"]').innerText()).replace(/\D+/g, "")),
    });

    // Event 5 — O201's 18 cases are already delivered.
    const open = await totals();
    expect(open.total, "the day is 96 cases").toBe(96);
    expect(open.delivered, "18 delivered").toBe(18);
    expect(open.remaining, "78 remaining").toBe(78);
    expect(open.delivered + open.remaining, "delivered + remaining = total").toBe(open.total);

    // Still exactly 96 after rev08 rearranges who carries what: a
    // superseded revision must never re-add an intermediate subtotal.
    await driveTo(page, sid, 10);
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev08", { timeout: 30_000 });
    const after = await totals();
    expect(after.total, "rev08 does not change the day's case count").toBe(96);
    expect(after.delivered, "O201 stays delivered under rev08").toBe(18);
    expect(after.remaining, "78 remain across Truck 2 and the partner").toBe(78);
  });

  test("place names are consistent and demo chrome is gone", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    await driveTo(page, sid, 22);

    const body = await page.locator("body").innerText();
    // Defensive demo chrome must not appear on the operating surfaces.
    for (const chrome of [
      /DETERMINISTIC TEST MODE/i,
      /SYNTHETIC TEST BANNER/i,
      /not derived from position/i,
      /no positions or bearings/i,
    ]) {
      expect(body, `demo chrome ${chrome} must be gone`).not.toMatch(chrome);
    }

    // The single disclosure lives in the Execution Record.
    await page.locator('[data-testid="open-execution-record"]').click();
    await expect(page.locator('[data-testid="synthetic-replay-disclosure"]')).toContainText(
      "Synthetic replay using configured facilities and planned reference routes.",
    );
  });

  // ===================================================================
  // v8 final filmability repair.
  // ===================================================================

  /** Marker badges currently drawn on the Google map, in DOM order. */
  async function markerBadges(page: Page): Promise<string[]> {
    return await page.evaluate(() => {
      const out: string[] = [];
      document.querySelectorAll('[data-testid="planned-dispatch-map"] [title]').forEach((a) => {
        const t = (a as HTMLElement).title || "";
        const m = /^((?:T1|T2|P)-\d+)/.exec(t);
        if (m) out.push(m[1]);
      });
      return out;
    });
  }

  test("event 5 markers match the two manifests exactly", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    expect(await cursor(page)).toBe(5);
    await expectMapSettled(page);

    const google = page.locator('[data-testid="planned-dispatch-map"]');
    if ((await google.count()) === 0) {
      test.skip(true, "no Maps key configured; marker identity is a Google-surface assertion");
    }

    // Ownership is the runtime's vehicle_id, so Truck 1 keeps all three
    // of its stops (including the delivered one) and Truck 2 keeps two.
    const badges = await markerBadges(page);
    expect([...badges].sort(), "T1-1..3 and T2-1..2, no duplicates").toEqual([
      "T1-1", "T1-2", "T1-3", "T2-1", "T2-2",
    ]);
    expect(new Set(badges).size, "no duplicate markers").toBe(badges.length);
  });

  test("delivered O201 keeps a marker after rev08, and partner reads P-1", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    await driveTo(page, sid, 10);
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev08", { timeout: 30_000 });
    await expectMapSettled(page);

    const google = page.locator('[data-testid="planned-dispatch-map"]');
    if ((await google.count()) === 0) {
      test.skip(true, "no Maps key configured; marker identity is a Google-surface assertion");
    }

    const titles = await page.evaluate(() =>
      Array.from(document.querySelectorAll('[data-testid="planned-dispatch-map"] [title]')).map(
        (a) => (a as HTMLElement).title || "",
      ),
    );
    // Berkeley's delivered commitment is still on the map and still named.
    expect(titles.join(" | "), "delivered O201 stays visible").toContain("O201");
    expect(titles.join(" | ")).toContain("Berkeley Community Pantry");
    // Partner fulfillment is numbered, never a bare "P-".
    expect(titles.some((t) => /^P-1\b/.test(t)), "partner marker reads P-1").toBe(true);
    expect(titles.some((t) => /^P-\s/.test(t) || /^P-$/.test(t)), "no bare P- marker").toBe(false);
  });

  test("event 21 renders the closure refusal, not a pending placeholder", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    await driveTo(page, sid, 21);
    await page.locator('[data-testid="nav-incident"]').click();

    const main = page.locator("main");
    await expect(main).toContainText("Closure refused — 8 cases remain unconfirmed", {
      timeout: 30_000,
    });
    await expect(page.locator('[data-testid="stage-pending"]')).toHaveCount(0);
    // Event 21 is the refusal; the terminal state belongs to event 22.
    await expect(page.locator('[data-testid="incident-status"]')).not.toHaveText(
      "PARTIALLY_CONTAINED",
    );
  });

  test("event 22 keeps the DENIED verdict above the fold and clear of Open work", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    await driveTo(page, sid, 22);
    await page.locator('[data-testid="nav-incident"]').click();

    const verdict = page.locator('[data-testid="refusal-verdict"]');
    await expect(verdict).toBeVisible({ timeout: 30_000 });
    await expect(verdict).toContainText("DENIED");
    await expect(verdict).toContainText("0");

    const v = (await verdict.boundingBox())!;
    expect(v.y, "verdict starts on screen").toBeGreaterThanOrEqual(0);
    expect(v.y + v.height, "the whole verdict tile is above y=900").toBeLessThanOrEqual(900);

    // The refusal headline remains the primary takeaway, above the verdict.
    const headline = (await page.locator("main h1").first().boundingBox())!;
    expect(headline.y, "headline precedes the verdict").toBeLessThan(v.y);

    // Open work must not overlap the verdict or the primary outcome.
    // Re-read the verdict box here so both rectangles are measured after
    // the same layout pass rather than comparing against a stale one.
    const v2 = (await verdict.boundingBox())!;
    const work = (await page.locator('[data-testid="work-to-do"]').boundingBox())!;
    expect(work.height, "Open work stays a compact strip").toBeLessThanOrEqual(180);
    // 1px tolerance: sub-pixel layout rounding, not a visible overflow.
    expect(work.y + work.height, "Open work stays inside the film frame").toBeLessThanOrEqual(901);
    // All four obligations are legible without scrolling.
    const aboveFold = await page.evaluate(
      () =>
        Array.from(document.querySelectorAll('[data-testid="work-item"]')).filter(
          (e) => e.getBoundingClientRect().bottom <= 900,
        ).length,
    );
    expect(aboveFold, "four obligations visible above fold").toBe(4);
    const overlaps = (a: typeof v, b: typeof v) =>
      a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
    expect(overlaps(work, v2), "Open work does not overlap the verdict").toBe(false);
    expect(overlaps(work, headline), "Open work does not overlap the headline").toBe(false);

    await expectNoHorizontalOverflow(page);
  });

  test("Fleet Activity stays a supporting column and keeps approval above fold", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);

    const rail = page.locator('[data-testid="fleet-activity-rail"]');
    const railBox = (await rail.boundingBox())!;
    expect(railBox.width, "rail is at most ~380px").toBeLessThanOrEqual(380);
    expect(railBox.width / 1600, "rail is under 25% of the viewport").toBeLessThan(0.25);

    // Bounded recent set, with the rest one click away.
    await driveTo(page, sid, 18);
    const shown = await page.locator('[data-testid="activity-entry"]').count();
    expect(shown, "only a bounded recent set is listed").toBeLessThanOrEqual(6);
    await expect(page.locator('[data-testid="view-earlier-activity"]')).toBeVisible();
    await page.locator('[data-testid="view-earlier-activity"]').click();
    expect(
      await page.locator('[data-testid="activity-entry"]').count(),
      "earlier activity expands",
    ).toBeGreaterThan(shown);

    // The approval action is still above fold at the gate.
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid2 = await sessionIdOf(page);
    await driveTo(page, sid2, 8);
    const approve = page.locator('[data-testid="approve-update"]');
    await expect(approve).toBeVisible({ timeout: 30_000 });
    const box = (await approve.boundingBox())!;
    expect(box.y + box.height, "approval is above fold at 900px").toBeLessThanOrEqual(900);
  });

  test("the Incidents badge tracks real open incidents", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    const badge = page.locator('[data-testid="incident-badge"]');

    // Before the failure there is nothing to badge.
    await expect(badge).toHaveCount(0);

    // 6-9: the truck failure is open.
    await driveTo(page, sid, 6);
    await expect(badge).toHaveText("1", { timeout: 30_000 });
    await driveTo(page, sid, 8);
    await expect(badge).toHaveText("1");

    // 10: rev08 resolves INC-2210, so the badge clears.
    await driveTo(page, sid, 10);
    await expect(badge, "resolved incident clears the badge").toHaveCount(0, { timeout: 30_000 });

    // 11 onward: the recall is open.
    await driveTo(page, sid, 11);
    await expect(badge).toHaveText("1", { timeout: 30_000 });

    // Partially contained is unresolved, so it keeps the badge. The
    // status itself lives inside the workspace, so confirm it there and
    // then come back to Today where the badge is rendered.
    await driveTo(page, sid, 22);
    await page.locator('[data-testid="nav-incident"]').click();
    await expect(page.locator('[data-testid="incident-status"]')).toHaveText("PARTIALLY_CONTAINED", {
      timeout: 30_000,
    });
    await page.locator('[data-testid="nav-today"]').click();
    await expect(badge).toHaveText("1");
  });

  test("defensive map language is gone and provider attribution is intact", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    await expectMapSettled(page);

    // Application-authored defensive copy must not appear.
    const body = await page.locator("body").innerText();
    for (const gone of [
      /NOT LIVE GPS/i,
      /CONFIGURED REFERENCE LOCATIONS/i,
      /CONFIGURED_REFERENCE/i,
      /configured reference locations/i,
      /not derived from position/i,
      /no positions or bearings/i,
    ]) {
      expect(body, `defensive copy ${gone} must be gone`).not.toMatch(gone);
    }

    // The OSM route attribution appears exactly once.
    const osm = (body.match(/Route geometry © OpenStreetMap contributors/g) ?? []).length;
    expect(osm, "OSM attribution appears once").toBe(1);

    // Google's own attribution must remain untouched where the map renders.
    if ((await page.locator('[data-testid="planned-dispatch-map"]').count()) === 1) {
      const google = await page.evaluate(() => {
        const host = document.querySelector('[data-testid="planned-dispatch-map"]');
        if (!host) return { terms: 0, watermark: 0 };
        return {
          terms: host.querySelectorAll('a[href*="google.com/intl"], a[href*="maps.google.com"]').length,
          watermark: host.querySelectorAll('img[src*="google"], a[title*="Google"]').length,
        };
      });
      expect(google.terms + google.watermark, "Google attribution is present").toBeGreaterThan(0);
    }
  });

  test("partner fulfillment uses one amber legend treatment", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    await driveTo(page, sid, 10);
    await expectMapSettled(page);

    const partner = page.locator('[data-testid="map-legend-partner"]');
    await expect(partner).toBeVisible({ timeout: 30_000 });

    // One solid colour, and no segmented/two-tone swatch.
    const swatch = await partner.locator("span").first().evaluate((el) => {
      const cs = getComputedStyle(el);
      return { bg: cs.backgroundColor, image: cs.backgroundImage };
    });
    expect(swatch.image, "no gradient/segmented partner swatch").toBe("none");

    // Distinct from both truck identities.
    const colors = await page.evaluate(async () => {
      const m = await import("/src/data/contract/routeGeometry.ts");
      return m.ROUTE_COLORS;
    });
    expect(colors.PARTNER).not.toBe(colors.TRUCK_1);
    expect(colors.PARTNER).not.toBe(colors.TRUCK_2);
  });

  test("Saturday drops the rejected headline and its footer does not overlap", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    await driveTo(page, sid, 24);
    await page.locator('[data-testid="saturday-ready-cta"]').click();
    await expectMapSettled(page);

    const main = page.locator("main");
    await expect(main).not.toContainText(/FRIDAY UNRESOLVED CARRIES FORWARD/i);
    await expect(main).not.toContainText(/no activation supported/i);
    await expect(page.locator('[data-testid="saturday-primary-message"]')).toContainText(
      "40 cases assigned",
    );
    await expect(page.locator('[data-testid="saturday-primary-message"]')).toContainText(
      "20 cases still unassigned",
    );

    // All four inherited obligations remain visible.
    for (const ref of ["BARRIER-4471", "SF-A03", "WORK-SITE01", "INC-2231"]) {
      await expect(main, `obligation ${ref} remains visible`).toContainText(ref);
    }

    // The footer sits in normal flow, above the fold, clear of the map.
    const footer = page.locator('[data-testid="map-location-disclosure"]').first();
    await expect(footer).toBeVisible();
    const f = (await footer.boundingBox())!;
    expect(f.y + f.height, "footer text is above the fold").toBeLessThanOrEqual(900);

    const mapBox = await page
      .locator('[data-testid="planned-dispatch-map"], [data-testid="dispatch-svg-schematic"]')
      .first()
      .boundingBox();
    if (mapBox) {
      expect(f.y, "footer sits below the map, not over it").toBeGreaterThanOrEqual(
        mapBox.y + mapBox.height - 2,
      );
    }

    await expectNoHorizontalOverflow(page);
  });

  test("autoplay dwells deliberately and ArrowRight cancels it", async ({ page }) => {
    // Public autoplay: the opening event must hold for several seconds
    // rather than flicking past.
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    expect(await cursor(page)).toBe(5);

    const started = Date.now();
    await expect.poll(() => cursor(page), { timeout: 20_000 }).toBeGreaterThan(5);
    const dwell = Date.now() - started;
    expect(dwell, "event 5 dwells about 5s before advancing").toBeGreaterThanOrEqual(4_000);

    // ArrowRight is deterministic: it cancels the pending tick, pauses,
    // and commits exactly one event.
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const before = await cursor(page);
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => cursor(page), { timeout: 20_000 }).toBe(before + 1);
    await page.waitForTimeout(4_000);
    expect(await cursor(page), "autoplay does not race the keypress").toBe(before + 1);
  });

  // -----------------------------------------------------------------
  // Single-flight transition control.
  // ---------------------------------------------------------------
  // Every frontend advancement path shares one controller. These tests
  // drive the REAL runtime and manipulate only network TIMING — no
  // canonical event, dwell interval, or application behaviour is
  // altered, and no test-only flag exists in the product.
  // -----------------------------------------------------------------

  /**
   * Hold `/advance` responses until released.
   *
   * Returns a handle that counts how many advance requests the page
   * actually opened — the direct measurement of "single flight" — and a
   * release for the first held response.
   */
  async function holdFirstAdvance(page: Page) {
    const handle = {
      opened: 0,
      concurrentPeak: 0,
      inFlight: 0,
      release: null as null | (() => void),
      released: false,
      /**
       * Release any still-held request and stop intercepting.
       *
       * A held request occupies a runtime handler thread, and an
       * interceptor left armed outlives the assertions it was for. Both
       * are released unconditionally so a failing assertion cannot leak
       * either into the next test.
       */
      async dispose() {
        handle.release?.();
        handle.released = true;
        await page.unroute("**/advance").catch(() => {});
      },
    };
    await page.route("**/advance", async (route) => {
      handle.opened += 1;
      handle.inFlight += 1;
      handle.concurrentPeak = Math.max(handle.concurrentPeak, handle.inFlight);
      if (!handle.released && handle.release === null) {
        await new Promise<void>((resolve) => {
          handle.release = () => {
            handle.released = true;
            resolve();
          };
        });
      }
      try {
        await route.continue();
      } catch {
        // The page navigated or closed under this request; nothing to do.
      } finally {
        handle.inFlight -= 1;
      }
    });
    return handle;
  }

  test("ArrowRight during an in-flight autoplay advance commits exactly one event", async ({
    page,
  }) => {
    const advance = await holdFirstAdvance(page);

    // Default autoplay — the ordinary product path, at the real dwell.
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    expect(await cursor(page), "opens at event 5").toBe(5);

    // Wait until the autoplay advance is genuinely in flight.
    await expect
      .poll(() => advance.opened, { timeout: 20_000, message: "autoplay opened /advance" })
      .toBe(1);

    const before = await cursor(page);
    expect(before, "the cursor has not moved yet: the request is still held").toBe(5);

    // The operator presses ArrowRight while that request is unresolved.
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(500);

    // No second request was opened: the keypress joined the one in flight.
    expect(advance.opened, "ArrowRight must not open a second /advance").toBe(1);
    expect(advance.concurrentPeak, "never more than one /advance in flight").toBe(1);

    advance.release?.();

    // Exactly one event, and it stays exactly one well beyond the next
    // dwell boundary — the longest dwell in the schedule is 6s.
    await expect.poll(() => cursor(page), { timeout: 20_000 }).toBe(before + 1);
    await page.waitForTimeout(8_000);
    expect(await cursor(page), "ArrowRight advances exactly once and stays paused").toBe(
      before + 1,
    );
    expect(advance.opened, "no further advance is dispatched while paused").toBe(1);
    await advance.dispose();
  });

  test("hammering ArrowRight and Space during a held advance never overlaps or skips", async ({
    page,
  }) => {
    const advance = await holdFirstAdvance(page);

    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const before = await cursor(page);
    await expect.poll(() => advance.opened, { timeout: 20_000 }).toBe(1);

    // Hammer both transports while the request is unresolved.
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press("ArrowRight");
      await page.keyboard.press("Space");
    }
    expect(advance.concurrentPeak, "no concurrent /advance under key hammering").toBe(1);

    advance.release?.();
    await page.waitForTimeout(6_000);

    // The runtime's own feed is the authority on what was committed. It
    // must be a gapless, strictly increasing canonical sequence: nothing
    // skipped, nothing duplicated, nothing reordered.
    const sid = await sessionIdOf(page);
    const feed = await feedOf(page, sid);
    const canonical = feed.filter((n) => Number.isFinite(n));
    for (let i = 1; i < canonical.length; i++) {
      expect(canonical[i], "committed events are strictly increasing and gapless").toBe(
        canonical[i - 1] + 1,
      );
    }
    expect(new Set(canonical).size, "no event is committed twice").toBe(canonical.length);

    // And the rendered cursor agrees with the runtime, having moved only
    // as far as the events actually committed.
    const rendered = await cursor(page);
    expect(rendered, "the rail never runs ahead of committed truth").toBe(
      canonical[canonical.length - 1],
    );
    expect(rendered, "hammering cannot skip events").toBeLessThanOrEqual(before + advance.opened);
    expect(advance.concurrentPeak).toBe(1);
    await advance.dispose();
  });

  test("a projection read that resolves out of order never overwrites newer state", async ({
    page,
  }) => {
    // The projection endpoint answers with the runtime's state at read
    // time. Holding one read and answering it with a genuinely older body
    // reproduces a real out-of-order resolution without changing the
    // runtime, the events, or the dwell schedule.
    // The opening-event body is captured once through the page's own
    // request context, so no intercepted response is held across the
    // hold — a disposed response would fail the interceptor itself.
    let openingBody: string | null = null;
    let release: null | (() => void) = null;
    let index = 0;

    await page.route("**/projection", async (route) => {
      const i = index++;
      if (i === 0) {
        // Record the opening state, then pass it through untouched.
        const response = await route.fetch();
        openingBody = await response.text();
        return route.fulfill({ status: 200, contentType: "application/json", body: openingBody });
      }
      if (i === 1) {
        // The read belonging to the first committed event. Hold it, then
        // answer it with the opening-event body: an older read landing
        // after newer ones have already rendered.
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: openingBody ?? "{}",
        });
      }
      return route.continue();
    });

    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    await expect
      .poll(() => release !== null, { timeout: 30_000, message: "a projection read is held" })
      .toBe(true);

    // The precondition this test needs is that NEWER projection reads have
    // already rendered while the older one is still held. Wait for that
    // condition rather than for a fixed interval, so a slow runtime makes
    // the test wait rather than assert against a state that never formed.
    await expect
      .poll(() => cursor(page), {
        timeout: 60_000,
        message: "progression rendered newer reads while an older one is held",
      })
      .toBeGreaterThan(6);

    // Pause through the supported path so the stale response is the LAST
    // write attempted against the rendered projection.
    await page.keyboard.press("Space");
    const heldCursor = await settleCursor(page, 1_000);
    const clockBefore = await page.locator('[data-testid="clock"]').innerText();
    const revBefore = await page.locator('[data-testid="auth-rev"]').innerText();
    expect(heldCursor, "progression moved past the held read").toBeGreaterThan(5);
    expect(clockBefore, "a real clock rendered before the stale read lands").not.toBe("—");

    release!();
    await page.waitForTimeout(2_500);
    // Stop intercepting before asserting, so the assertions read a page
    // served by the real runtime and no interceptor outlives this test.
    await page.unroute("**/projection").catch(() => {});

    // The stale body is dropped: nothing regresses, and nothing jumps.
    expect(await page.locator('[data-testid="clock"]').innerText(), "a stale read never regresses the clock").toBe(clockBefore);
    expect(await page.locator('[data-testid="auth-rev"]').innerText(), "a stale read never regresses the revision").toBe(revBefore);
    expect(await cursor(page), "a stale read never moves the cursor").toBe(heldCursor);
    await expectNoFutureCanonical(page, heldCursor);
  });

  test("pausing default autoplay holds the cursor beyond the longest dwell", async ({ page }) => {
    // The supported application path: default autoplay, paused with the
    // product's own Space transport. No API pause, no injected flag.
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    expect(await cursor(page)).toBe(5);

    await page.keyboard.press("Space");
    const held = await settleCursor(page, 1_000);

    // The longest dwell in the schedule is 6s; wait well past it. A timer
    // that had already fired must still refuse to dispatch.
    await page.waitForTimeout(12_000);
    expect(await cursor(page), "a paused session commits nothing past any dwell boundary").toBe(
      held,
    );

    // Resume arms exactly one chain, and the session moves again.
    await page.keyboard.press("Space");
    await expect
      .poll(() => cursor(page), { timeout: 20_000, message: "resume restarts progression" })
      .toBeGreaterThan(held);
  });

  test("bare R does not reset; Shift+R is the reset gesture", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });
    const sid = await sessionIdOf(page);
    await driveTo(page, sid, 12);
    const held = await settleCursor(page);

    // A stray "r" during a rehearsal must not wipe the take.
    await page.keyboard.press("KeyR");
    await page.waitForTimeout(1_500);
    expect(await cursor(page), "bare R is inert").toBe(held);
    // No visible reset control exists in presenter mode.
    await expect(page.locator('[data-testid="debug-reset"]')).toHaveCount(0);
  });

});

// ---------------------------------------------------------------------

/** Read the live session id the page created, from the runtime itself. */
async function sessionIdOf(page: Page): Promise<string> {
  // The app stores it on the element it renders the cursor onto; read the
  // runtime's own session list instead of reaching into React state.
  return await page.evaluate(async () => {
    const w = window as unknown as { __FS_SESSION_ID?: string };
    return w.__FS_SESSION_ID ?? "";
  });
}

/**
 * Drive the real runtime to a target cursor, approving at the human gate,
 * and wait for the UI to reflect it. Uses the runtime's own endpoints —
 * never a mock — so the UI is always reacting to committed events.
 */
async function driveTo(page: Page, sid: string, target: number) {
  await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/pause`).catch(() => {});

  for (let guard = 0; guard < 40; guard++) {
    const state = await (await page.request.get(`${RUNTIME}/api/v1/replay/sessions/${sid}`)).json();
    if (state.cursor >= target) break;

    const res = await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/advance`);
    if (res.status() === 409) {
      const detail = (await res.json()).detail;
      if (detail === "HUMAN_APPROVAL_REQUIRED") {
        // Approve through the REAL UI control, not the API: the visible
        // human action is part of what this suite must prove.
        const approve = page.locator('[data-testid="approve-update"]');
        await expect(approve).toBeVisible({ timeout: 30_000 });
        await approve.click();
        await expect
          .poll(async () =>
            (await (await page.request.get(`${RUNTIME}/api/v1/replay/sessions/${sid}`)).json()).cursor,
          { timeout: 30_000 })
          .toBeGreaterThanOrEqual(9);
        continue;
      }
      if (detail === "REPLAY_COMPLETE") break;
      throw new Error(`advance refused: ${detail}`);
    }
  }

  await waitForCursor(page, target, 60_000);
}
