// =====================================================================
// Full Shelf — the canonical partner reply on "5 Decide closure"
// ---------------------------------------------------------------------
// The eight East Bay cases stay unconfirmed because the partner's 10:11
// reply did not establish custody. That reason is canonical Friday
// history, so it must be readable on the closure stage itself — without
// opening the Evidence drawer or any other surface.
//
// Runs against the REAL React UI and the REAL Golden Runtime Controller
// on 127.0.0.1:8788. No mock, no stub. Captured at 1600×900.
// =====================================================================

import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const UPDATE_GOLDEN = process.env.UPDATE_GOLDEN_SCREENSHOTS === "1";
const SHOTS = UPDATE_GOLDEN ? "e2e/screenshots/golden" : "test-results/partner-evidence";

test.setTimeout(180_000);

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));

const cursor = async (page: Page): Promise<number> =>
  Number(await page.locator('[data-testid="app-root"]').getAttribute("data-cursor"));

/**
 * Drive the canonical timeline to the closure decision and open its stage.
 *
 * The approval gate at event 8 is crossed the only way it can be: by a
 * human clicking the real control. Autoplay cannot pass it, which is the
 * point of the gate, so the test acts as the operator does.
 */
async function atClosureStage(page: Page) {
  await page.goto("/");
  await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });

  // Event 8 raises the human gate and progression stops there.
  const approve = page.locator('[data-testid="approve-update"]');
  await expect(approve).toBeVisible({ timeout: 60_000 });
  await approve.click();

  // Event 11 then holds until the operator opens Incidents.
  await expect.poll(() => cursor(page), { timeout: 60_000 }).toBeGreaterThanOrEqual(11);
  await page.locator('[data-testid="nav-incident"]').click();
  await expect.poll(() => cursor(page), { timeout: 90_000 }).toBeGreaterThanOrEqual(21);
  await page.locator('[data-testid="stage-closure"]').click();
  await expect(page.locator('[data-testid="partner-response-evidence"]')).toBeVisible();
}

test.describe("Canonical partner evidence", () => {
  test("the reply and every missing field are readable on Decide closure", async ({ page }) => {
    await atClosureStage(page);
    const card = page.locator('[data-testid="partner-response-evidence"]');

    // 1. The exact partner message, quoted verbatim.
    await expect(page.locator('[data-testid="partner-response-text"]')).toHaveText(
      /We pulled the remaining lettuce\. Should be all good\./,
    );
    await expect(card).toContainText("East Bay Distribution Annex");
    await expect(card).toContainText("authenticated partner callback");
    await expect(card).toContainText("10:11 AM");

    // 2. All five required evidence fields are visible as missing.
    await expect(card).toContainText("EVIDENCE INSUFFICIENT");
    for (const [key, label] of [
      ["lot", "Lot ID"],
      ["quantity", "Quantity"],
      ["location", "Confirmed location"],
      ["disposition", "Qualifying disposition"],
      ["confirmation_time", "Confirmation time"],
    ]) {
      await expect(page.locator(`[data-testid="missing-claim-${key}"]`)).toHaveText(label);
    }

    // 3. Partner Operations read intent; it did not decide policy.
    await expect(card).toContainText("Partner Operations read likely containment intent");
    await expect(card).toContainText(
      "does not satisfy the evidence required to confirm custody",
    );

    // 4-6. Recorded as evidence; custody and the acknowledgment unchanged.
    await expect(page.locator('[data-testid="partner-evidence-footer"]')).toHaveText(
      "Reply recorded · Custody remains 88/96 · Acknowledgment remains open",
    );

    // 7-8. Closure stays blocked, and the refusal still proves zero mutations.
    await expect(page.locator('[data-testid="dominant-section"]')).toContainText(
      "remain unconfirmed because the partner response does not satisfy the custody evidence requirement",
    );
    const verdict = page.locator('[data-testid="refusal-verdict"]');
    await expect(verdict).toContainText("DENIED");
    await expect(verdict).toContainText("PARTIALLY_CONTAINED");

    // The reason needs no second surface: the drawer is still shut.
    await expect(page.locator('[data-testid="execution-record-drawer"]')).toHaveCount(0);
  });

  test("the closure stage fits 1600x900 without clipping", async ({ page }) => {
    await atClosureStage(page);

    const { scrollW, clientW } = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    expect(scrollW, "no horizontal overflow at 1600×900").toBeLessThanOrEqual(clientW);

    const box = await page.locator('[data-testid="partner-response-evidence"]').boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(120);
    expect(box!.x + box!.width).toBeLessThanOrEqual(1600);

    // The refusal proof stays immediately adjacent — same stage, same
    // scroll body, within one viewport height of the card.
    const verdict = await page.locator('[data-testid="refusal-verdict"]').boundingBox();
    expect(verdict).not.toBeNull();
    expect(verdict!.y + verdict!.height, "the refusal proof stays adjacent")
      .toBeLessThanOrEqual(900);
    expect(Math.abs(verdict!.y - box!.y), "card and refusal proof stay adjacent")
      .toBeLessThanOrEqual(900);


    // boundingBox alone is NOT enough: an element inside a scrolling
    // container reports coordinates within the viewport while still
    // being clipped out of sight. This asserts what the operator can
    // actually see — the element's rect against every ancestor's.
    const fullyVisible = (testId: string) =>
      page.locator(`[data-testid="${testId}"]`).evaluate((el) => {
        const r = el.getBoundingClientRect();
        if (r.bottom > window.innerHeight || r.top < 0) return false;
        for (let n = el.parentElement; n; n = n.parentElement) {
          const s = getComputedStyle(n);
          if (s.overflowY === "visible" && s.overflowX === "visible") continue;
          const c = n.getBoundingClientRect();
          if (r.bottom > c.bottom + 1 || r.top < c.top - 1) return false;
        }
        return true;
      });

    // The card sits under the three numbered cards in the left column,
    // inside the stage's own scrolling body. Scroll it into view as an
    // operator would, then assert the whole thing is legible — quote,
    // all five missing fields, and the state footer.
    await page.locator('[data-testid="partner-response-evidence"]')
      .scrollIntoViewIfNeeded();
    expect(await fullyVisible("partner-response-text"),
      "the partner message must be readable").toBe(true);
    expect(await fullyVisible("missing-claim-confirmation_time"),
      "every missing evidence field must be scannable").toBe(true);
    expect(await fullyVisible("partner-evidence-footer"),
      "the state footer must be visible").toBe(true);

    await page.screenshot({ path: `${SHOTS}/closure-partner-evidence.png` });
  });

  test("presenter controls and event numbering are unchanged", async ({ page }) => {
    await page.goto("/?presenter=1");
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 30_000 });

    // Presenter still opens PAUSED at event 5 with no visible transport.
    expect(await cursor(page)).toBe(5);
    await expect(
      page.getByRole("button", { name: /^(play|pause|advance|step|next event|reset)$/i }),
    ).toHaveCount(0);

    // ArrowRight still commits exactly one event.
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => cursor(page), { timeout: 15_000 }).toBe(6);
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => cursor(page), { timeout: 15_000 }).toBe(7);

    // Space toggles autoplay, and the gate at 8 still holds for a human.
    await page.keyboard.press("Space");
    await expect.poll(() => cursor(page), { timeout: 20_000 }).toBe(8);
    await page.waitForTimeout(3_000);
    expect(await cursor(page), "autoplay may not cross the approval gate").toBe(8);
    await expect(page.locator('[data-testid="approve-update"]')).toBeVisible();
  });
});

// ---------------------------------------------------------------------
// The recall holds until the operator starts it.
//
// This is a BEHAVIORAL test on purpose. The regression it guards was
// invisible to source assertions: the hold flag was set, the banner
// rendered, and the runtime was paused — while the frontend ticker,
// which is what actually paces the day, carried the cursor from 11 to
// 17 with nobody pressing anything. Only watching the real cursor over
// real idle time catches that.
// ---------------------------------------------------------------------

const cursorOf = async (page: Page): Promise<number> =>
  Number(await page.locator('[data-testid="app-root"]').getAttribute("data-cursor"));

/** Autoplay to the recall notice, having crossed the approval gate. */
async function atRecallNotice(page: Page, parkOnIncidents: boolean) {
  await page.goto("/");
  const approve = page.locator('[data-testid="approve-update"]');
  await expect(approve).toBeVisible({ timeout: 60_000 });
  await approve.click();
  if (parkOnIncidents) {
    await expect.poll(() => cursorOf(page), { timeout: 60_000 }).toBeGreaterThanOrEqual(10);
    await page.locator('[data-testid="nav-incident"]').click();
  }
  await expect.poll(() => cursorOf(page), { timeout: 60_000 }).toBeGreaterThanOrEqual(11);
}

test.describe("The recall waits for the operator", () => {
  test("holds at event 11 on Today until Open Incidents is pressed", async ({ page }) => {
    await atRecallNotice(page, false);
    expect(await cursorOf(page)).toBe(11);

    // Idle far longer than any dwell. Nothing may advance on its own.
    await page.waitForTimeout(10_000);
    expect(await cursorOf(page), "the recall must not start itself").toBe(11);

    await expect(page.locator('[data-testid="recall-pause-banner"]')).toBeVisible();
    await page.locator('[data-testid="open-incidents-cta"]').click();
    await expect.poll(() => cursorOf(page), { timeout: 20_000 }).toBeGreaterThan(11);
  });

  test("holds even when the operator is already on Incidents", async ({ page }) => {
    // The regression: being on the view was treated as consent, so the
    // recall started without anyone asking for it.
    await atRecallNotice(page, true);
    expect(await cursorOf(page)).toBe(11);

    await page.waitForTimeout(10_000);
    expect(await cursorOf(page), "presence on a view is not a decision").toBe(11);

    // The Today banner does not render here, so the workspace carries its
    // own start control.
    const start = page.locator('[data-testid="start-recall-response"]');
    await expect(start).toBeVisible();
    await start.click();
    await expect.poll(() => cursorOf(page), { timeout: 20_000 }).toBeGreaterThan(11);
  });
});
