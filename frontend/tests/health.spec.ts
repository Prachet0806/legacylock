import { test, expect } from "@playwright/test";

test("health page renders", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("LegacyLock")).toBeVisible();
});
