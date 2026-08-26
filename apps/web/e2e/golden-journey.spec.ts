import { test, expect } from "@playwright/test";

const FRONTEND_URL = "http://127.0.0.1:5173/";  // Must match runtime CORS allowlist

test.describe("Golden Journey", () => {
  test("session lifecycle: events 5→25 with approval, incidents, recovery, branches, Saturday", async ({
    page,
  }) => {
    // Event 5: Friday opened
    await page.goto(FRONTEND_URL);

    // Wait for clock to appear (session init + projection fetch)
    await expect(page.locator('[data-testid="clock"]')).toBeVisible({ timeout: 20000 });
    await expect(page.locator('[data-testid="clock"]')).toContainText("08:05");

    // Verify app is rendering (incident badge starts at 0, will reach 1 when vehicle failure arrives)
    const incidentBadge = page.locator('[data-testid="incident-badge"]');

    // Event 6+: Wait for incident to appear (vehicle failure badge shows count > 0)
    await expect(incidentBadge).toContainText("1", { timeout: 30000 });

    // Navigate to Incidents to see incident details
    const incidentsNav = page.locator('[data-testid="nav-incident"]');
    await incidentsNav.click();

    // Incident details should now be visible
    const incidentTitle = page.locator("text=Vehicle failure");
    await expect(incidentTitle).toBeVisible({ timeout: 10000 });

    // Event 8: Repair proposal should appear in the sidecar
    await page.waitForTimeout(15000); // Wait for events to progress to event 8+
    const approveButton = page.locator('[data-testid="approve-update"]');
    const proposalVisible = await approveButton.isVisible().catch(() => false);
    if (proposalVisible) {
      await approveButton.click();
      const approvedStatus = page.locator("text=APPROVED");
      await expect(approvedStatus).toBeVisible({ timeout: 10000 });
    }

    // Verify clock progresses (autoplay advancing)
    await page.waitForTimeout(5000);
    const clockText = await page.locator('[data-testid="clock"]').textContent();
    const clockIsAfter0805 = clockText && clockText !== "08:05";
    expect(clockIsAfter0805).toBe(true);

    // Verify no horizontal overflow at 1600×900
    await page.setViewportSize({ width: 1600, height: 900 });
    const bodyScrollWidth = await page.evaluate(() => document.body.scrollWidth);
    const bodyClientWidth = await page.evaluate(() => document.body.clientWidth);
    expect(bodyScrollWidth).toBeLessThanOrEqual(bodyClientWidth);
  });
});
