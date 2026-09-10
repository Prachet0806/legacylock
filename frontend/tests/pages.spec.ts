import { test, expect } from "@playwright/test";

const pages: Array<[string, string]> = [
  ["/", "LegacyLock"],
  ["/login", "Owner login"],
  ["/vault", "Unlock vault"],
  ["/vault/setup", "Vault setup"],
  ["/beneficiaries", "Beneficiaries"],
  ["/heartbeat", "Heartbeat"],
  ["/recovery", "Beneficiary recovery"],
];

for (const [path, heading] of pages) {
  test(`${path} renders`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  });
}

test("/access/invite/[hash] renders", async ({ page }) => {
  await page.goto("/access/invite/deadbeef");
  await expect(page.getByRole("heading", { name: "Beneficiary invitation" })).toBeVisible();
});
