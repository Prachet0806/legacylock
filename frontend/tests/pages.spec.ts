import { test, expect } from "@playwright/test";

// Public routes render without a session.
test("/ renders login", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Owner login" })).toBeVisible();
});

test("/access/invite/[hash] renders", async ({ page }) => {
  await page.goto("/access/invite/deadbeef");
  await expect(page.getByRole("heading", { name: "Beneficiary invitation" })).toBeVisible();
});

// Protected routes bounce logged-out visitors to / (login).
const PROTECTED = ["/home", "/vault", "/vault/setup", "/beneficiaries", "/heartbeat", "/recovery", "/settings"];

for (const path of PROTECTED) {
  test(`${path} redirects logged-out visitors to /`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: "Owner login" })).toBeVisible();
  });
}

test("/login redirects to /", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Owner login" })).toBeVisible();
});

test("/recovery renders gate for token-carrying beneficiaries", async ({ page }) => {
  // The intended auth-bypass exception: a tab-scoped invite token admits the
  // recovery page itself (the backend still 403s every API call).
  await page.addInitScript(() => {
    sessionStorage.setItem("legacylock_beneficiary_token", "test-token");
  });
  await page.goto("/recovery");
  await expect(page).toHaveURL(/\/recovery$/);
  await expect(page.getByRole("heading", { name: "Beneficiary recovery" })).toBeVisible();
});
