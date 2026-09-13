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

// Protected routes bounce logged-out visitors to / (login). Generous timeout:
// the guard probes getMe() then (on /recovery) getAccessStatus(), and dev
// cold-compile adds seconds on first hit.
const PROTECTED = ["/home", "/vault", "/vault/setup", "/beneficiaries", "/heartbeat", "/recovery", "/settings"];

for (const path of PROTECTED) {
  test(`${path} redirects logged-out visitors to /`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveURL(/\/$/, { timeout: 15000 });
    await expect(page.getByRole("heading", { name: "Owner login" })).toBeVisible();
  });
}

test("/login redirects to /", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Owner login" })).toBeVisible();
});

test("stale sessionStorage token does NOT admit /recovery", async ({ page }) => {
  // Regression: the shell must not guess beneficiary status from storage.
  // Admission requires a live beneficiary session (proven by golden.spec.ts).
  await page.addInitScript(() => {
    sessionStorage.setItem("legacylock_beneficiary_token", "test-token");
  });
  await page.goto("/recovery");
  await expect(page).toHaveURL(/\/$/, { timeout: 15000 });
  await expect(page.getByRole("heading", { name: "Owner login" })).toBeVisible();
});
