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

    // Event 6: Truck failure
    const failureHeadline = page.locator("text=Truck 1 refrigeration failure");
    await expect(failureHeadline).toBeVisible({ timeout: 20000 });

    // Event 8: Repair proposed (approval gate)
    const proposalHeadline = page.locator("text=Proposed update to the active plan");
    await expect(proposalHeadline).toBeVisible({ timeout: 20000 });
    const approveButton = page.locator('[data-testid="approve-update"]');
    await expect(approveButton).toBeVisible();

    // Event 9: Approval submitted
    await approveButton.click();
    const approvedStatus = page.locator("text=APPROVED");
    await expect(approvedStatus).toBeVisible({ timeout: 10000 });

    // Event 10: rev08 active
    const rev08Headline = page.locator("text=rev08 active");
    await expect(rev08Headline).toBeVisible({ timeout: 10000 });

    // Event 11: Pause on Today
    await page.waitForTimeout(3000);
    const recallHeadline = page.locator("text=Recall notice received");
    await expect(recallHeadline).not.toBeVisible();

    // Click Incidents to resume
    const incidentsNav = page.locator('[data-testid="nav-incident"]');
    await incidentsNav.click();
    await expect(recallHeadline).toBeVisible({ timeout: 10000 });
    const incidentBadge = page.locator('[data-testid="incident-badge"]');
    await expect(incidentBadge).toContainText("1");

    // Event 22+: Partially contained
    const partiallyContainedHeadline = page.locator("text=PARTIALLY_CONTAINED");
    await expect(partiallyContainedHeadline).toBeVisible({ timeout: 30000 });

    // Saturday
    const fridayButton = page.locator('[data-testid="day-fri"]');
    await fridayButton.click();
    const saturdayButton = page.locator('[data-testid="day-sat"]');
    await saturdayButton.click();
    const saturdayDraftHeadline = page.locator("text=Saturday · Draft");
    await expect(saturdayDraftHeadline).toBeVisible({ timeout: 10000 });

    // Verify no horizontal overflow at 1600×900
    await page.setViewportSize({ width: 1600, height: 900 });
    const bodyScrollWidth = await page.evaluate(() => document.body.scrollWidth);
    const bodyClientWidth = await page.evaluate(() => document.body.clientWidth);
    expect(bodyScrollWidth).toBeLessThanOrEqual(bodyClientWidth);
  });
});
