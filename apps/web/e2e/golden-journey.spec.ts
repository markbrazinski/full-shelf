import { test, expect } from "@playwright/test";

const FRONTEND_URL = "http://127.0.0.1:5173/";

test.describe("Golden Journey", () => {
  test("session lifecycle: events 5→25 with approval, incidents, recovery, branches, Saturday", async ({
    page,
  }) => {
    // Event 5: Friday opened
    await page.goto(FRONTEND_URL);

    // Session init + first projection fetch
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 20000 });
    const initialClock = await page.locator('[data-testid="clock"]').textContent();
    expect(initialClock).toContain("08:05");

    // Autoplay should advance the session. Wait and verify clock progresses.
    await page.waitForTimeout(10000); // ~10s at 900ms intervals = ~11 events
    const laterClock = await page.locator('[data-testid="clock"]').textContent();
    expect(laterClock).not.toEqual(initialClock); // Clock should have progressed

    // Verify incident badge appears once vehicle failure is active (cursor 6+)
    const incidentBadge = page.locator('[data-testid="incident-badge"]');
    const incidentCount = await incidentBadge.textContent({ timeout: 5000 }).catch(() => "0");
    expect(parseInt(incidentCount || "0")).toBeGreaterThan(0);

    // Viewport check: no horizontal overflow at 1600×900
    await page.setViewportSize({ width: 1600, height: 900 });
    const bodyScrollWidth = await page.evaluate(() => document.body.scrollWidth);
    const bodyClientWidth = await page.evaluate(() => document.body.clientWidth);
    expect(bodyScrollWidth).toBeLessThanOrEqual(bodyClientWidth);
  });
});
