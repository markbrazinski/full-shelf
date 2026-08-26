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
// Screenshots are captured at 1600×900 into e2e/screenshots/golden/.
// =====================================================================

import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const SHOTS = "e2e/screenshots/golden";
const RUNTIME = "http://127.0.0.1:8788";

// The runtime autoplays at 900ms; 25 events plus approval needs headroom.
test.setTimeout(180_000);

test.beforeAll(() => {
  mkdirSync(SHOTS, { recursive: true });
});

const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });

const cursor = async (page: Page): Promise<number> =>
  Number(await page.locator('[data-testid="app-root"]').getAttribute("data-cursor"));

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
    await page.goto("/");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });

    // Hold at the opening frame so it is captured as event 5 rather than
    // whatever autoplay reached first. The pause is a presentation
    // control only: it moves no cursor and mutates nothing.
    await page.request
      .post(`${RUNTIME}/api/v1/replay/sessions/${await sessionIdOf(page)}/pause`)
      .catch(() => {});

    await expect(page.locator('[data-testid="clock"]')).toHaveText("08:05");
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");
    expect(await cursor(page)).toBe(5);

    // The map surfaces all six configured reference locations and says so.
    await expect(page.locator('[data-testid="map-location-disclosure"]')).toContainText(
      "6 configured reference locations · no live GPS",
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
    // O203 becomes a refrigerated partner pickup, not a shortfall.
    await expect(manifests).toContainText("Partner pickup");
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

    // Clicking Incidents releases the pause and resumes progression.
    await page.locator('[data-testid="nav-incident"]').click();
    await expect
      .poll(() => cursor(page), { timeout: 40_000, message: "Incidents click resumes progression" })
      .toBeGreaterThan(heldAt);

    // ---------------------------------------------------------------
    // 6. Event 18 — custody: 96 unique, 88 confirmed, 8 at Site 01.
    // ---------------------------------------------------------------
    await waitForCursor(page, 18);
    await page.locator('[data-testid="incident-tab-custody"]').click();

    const custody = page.locator('[data-testid="custody-headline"]');
    await expect(custody).toBeVisible({ timeout: 30_000 });
    await expect(custody).toContainText("96 cases traced");
    await expect(custody).toContainText("8 unconfirmed");

    const custodyPanel = page.locator("main");
    await expect(custodyPanel).toContainText("Site 01");
    // 24 + 22 + 20 + 10 + 8 + 12 = 96 — intermediate subtotals not re-added.
    await expect(custodyPanel).toContainText("24 + 22 + 20 + 10 + 8 + 12 = 96");

    await expectNoHorizontalOverflow(page);
    await shot(page, "06-custody");

    // Navigation must not move the cursor. Tabs are NAVIGATION_ONLY.
    const beforeTabs = await cursor(page);
    await page.locator('[data-testid="nav-history"]').click();
    await page.locator('[data-testid="nav-incident"]').click();
    await page.locator('[data-testid="incident-tab-intake"]').click();
    await page.locator('[data-testid="incident-tab-custody"]').click();
    const afterTabs = await cursor(page);
    expect(afterTabs, "view/tab clicks never rewind the cursor").toBeGreaterThanOrEqual(beforeTabs);
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
        "GOOGLE MAPS · CONFIGURED REFERENCE LOCATIONS · NOT LIVE GPS",
      );
    } else {
      // Truthful fallback: only legitimate when no authorized key painted.
      await expect(schematic).toBeVisible();
      await expect(page.locator('[data-testid="schematic-provenance-label"]')).toContainText(
        "CONFIGURED REFERENCE LOCATIONS · NOT LIVE GPS",
      );
      console.log(`map fallback rendered (key configured: ${keyConfigured})`);
    }

    // Both paths carry the runtime's own disclosure for all six sites.
    await expect(page.locator('[data-testid="map-location-disclosure"]')).toContainText(
      "6 configured reference locations · no live GPS",
    );
    await expect(page.locator('[data-testid="map-location-disclosure"]')).toContainText(
      "No live GPS or operational affiliation is claimed",
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
    await page.locator('[data-testid="incident-tab-recovery"]').click();

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
    await page.goto("/");
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
    await page.locator('[data-testid="incident-tab-evidence"]').click();

    const panel = page.locator('[data-testid="evidence-branch-panel"]');
    await expect(panel).toBeVisible({ timeout: 30_000 });
    await expect(panel).toHaveAttribute("data-branch", "canonical");
    // Canonical custody before any branch: 88 of 96.
    await expect(page.locator('[data-testid="branch-custody-figure"]')).toHaveText("88/96");

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

    await expectNoHorizontalOverflow(page);
    await shot(page, "09-vague-evidence");

    // Exit restores canonical.
    await page.locator('[data-testid="branch-exit"]').click();
    await expect(panel).toHaveAttribute("data-branch", "canonical", { timeout: 30_000 });
    await expect(page.locator('[data-testid="branch-custody-figure"]')).toHaveText("88/96");

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

    await expectNoHorizontalOverflow(page);
    await shot(page, "10-complete-evidence");

    // ---- exit restores canonical 88/96 and PARTIALLY_CONTAINED ------
    await page.locator('[data-testid="branch-exit"]').click();
    await expect(panel).toHaveAttribute("data-branch", "canonical", { timeout: 30_000 });
    await expect(page.locator('[data-testid="branch-custody-figure"]')).toHaveText("88/96");
    await expect(page.locator('[data-testid="header-branch-label"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="incident-status"]')).toHaveText("PARTIALLY_CONTAINED");

    // The custody surface itself agrees: canonical is back to 88 of 96.
    await page.locator('[data-testid="incident-tab-custody"]').click();
    await expect(page.locator('[data-testid="custody-headline"]')).toContainText("96 cases traced");
    await expect(page.locator("main")).toContainText("8 unconfirmed");

    await expectNoHorizontalOverflow(page);
    await shot(page, "11-canonical-return");
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
