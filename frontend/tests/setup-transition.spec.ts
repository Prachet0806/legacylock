import { expect, test } from "@playwright/test";

test("finalizing setup binds the new revision before opening the vault", async ({ page }) => {
  let material: Record<string, unknown> = { material_revision: 0, wrapped_vmk: null };
  let finalized = false;
  let authChecks = 0;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let body: object = {};
    if (path === "/api/auth/me") {
      authChecks++;
      body = { id: 1, email: "owner@example.com" };
    } else if (path === "/api/vault/crypto-material" && method === "GET") {
      body = material;
    } else if (path === "/api/vault/recovery-ceremony" && method === "POST") {
      const request = route.request().postDataJSON();
      material = { ...request.initial_material, material_revision: 1 };
      body = { ceremony_id: 7, material_revision: 1, recovery_threshold: 2, recovery_total: 3 };
    } else if (path === "/api/vault/recovery-ceremony/7/finalize" && method === "POST") {
      finalized = true;
      body = { material_revision: 1 };
    } else if (path === "/api/vault/readiness") {
      body = {
        initialized: finalized, material_revision: finalized ? 1 : 0,
        ceremony_status: finalized ? "READY" : "NONE", quorum_assigned: false,
        owner_reported_drill: null, threshold: 2, total: 3,
      };
    } else if (path === "/api/vault/status") {
      body = { status: "active", armed: false, release_hold: true };
    } else if (path === "/api/heartbeat") {
      body = { armed: false, last_check_in: null, interval_days: 30, grace_days: 7 };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/vault/setup");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Vault passphrase").fill("setup-transition-passphrase-1234");
  await page.getByLabel("Confirm passphrase").fill("setup-transition-passphrase-1234");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Generate vault key" }).click();
  for (const index of [1, 2, 3]) {
    await page.getByRole("button", { name: `Go to share ${index}`, exact: true }).click();
    await expect(page.getByTestId(`share-${index}`)).toBeVisible();
    await page.getByRole("button", { name: "I've stored this safely", exact: true }).click();
  }
  const beforeFinalization = authChecks;
  await page.getByRole("button", { name: "Complete setup" }).click();
  await expect(page).toHaveURL(/\/vault$/);
  await expect(page.getByRole("button", { name: "Unlock vault", exact: true })).toBeVisible();
  expect(finalized).toBe(true);
  expect(authChecks).toBeGreaterThan(beforeFinalization);
});
