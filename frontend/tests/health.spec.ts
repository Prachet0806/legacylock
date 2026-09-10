import { test, expect } from "@playwright/test";

test("brand link is visible on login", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("LegacyLock").first()).toBeVisible();
});
