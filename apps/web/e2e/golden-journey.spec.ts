// =====================================================================
// Golden Journey E2E Test
// =====================================================================
// Real session-based journey against Golden Runtime Controller (8788).
// Complete canonical path: event 5 through 25.

import { test, expect } from "@playwright/test";

const FRONTEND_URL = "http://localhost:5173/";

test.describe("Golden Journey", () => {
  test("session lifecycle: healthy → failure → approval → incidents → recovery → branches → Saturday", async ({
    page,
  }) => {
    // Event 5: Friday opened
    await page.goto(FRONTEND_URL);
    await expect(page.locator('[data-testid="clock"]')).toContainText("08:05", {
      timeout: 5000,
    });

    // Event 6: Truck failure
    const failureHeadline = page.locator("text=Truck 1 refrigeration failure");
    await expect(failureHeadline).toBeVisible({ timeout: 15000 });

    // Event 8: Repair proposed (approval gate)
    const proposalHeadline = page.locator("text=Proposed update to the active plan");
    await expect(proposalHeadline).toBeVisible({ timeout: 15000 });
    const approveButton = page.locator('[data-testid="approve-update"]');
    await expect(approveButton).toBeVisible();

    // Event 9: Approval submitted
    await approveButton.click();
    const approvedStatus = page.locator("text=APPROVED");
    await expect(approvedStatus).toBeVisible({ timeout: 10000 });

    // Event 10: rev08 active
    const rev08Headline = page.locator("text=rev08 active");
    await expect(rev08Headline).toBeVisible({ timeout: 10000 });

    // Event 11: Pause on Today (until Incidents clicked)
    await page.waitForTimeout(2000);
    const recallHeadline = page.locator("text=Recall notice received");
    await expect(recallHeadline).not.toBeVisible();

    // Click Incidents to resume
    const incidentsNav = page.locator('[data-testid="nav-incident"]');
    await incidentsNav.click();
    await expect(recallHeadline).toBeVisible({ timeout: 10000 });
    const incidentBadge = page.locator('[data-testid="incident-badge"]');
    await expect(incidentBadge).toContainText("1");

    // Event 18+: Custody tab
    const custodyTab = page.locator('text="Custody"');
    await expect(custodyTab).toBeVisible({ timeout: 5000 });
    await custodyTab.click();
    const custodyHeadline = page.locator("text=How much was affected");
    await expect(custodyHeadline).toBeVisible({ timeout: 15000 });

    // Event 22: Partially contained
    const partiallyContainedHeadline = page.locator("text=PARTIALLY_CONTAINED");
    await expect(partiallyContainedHeadline).toBeVisible({ timeout: 20000 });

    // Event 24: Saturday draft
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
