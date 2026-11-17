import { expect, test } from "@playwright/test";

const beneficiaryStatus = {
  beneficiary_id: 7,
  material_revision: 3,
  vault_status: "triggered",
  vault_name: "Test vault",
  share_index: 1,
  recovery_threshold: 2,
  recovery_total: 3,
};

test("beneficiary access expires through its own refresh endpoint", async ({ page }) => {
  const calls = new Map<string, number>();
  let valid = true;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.set(path, (calls.get(path) ?? 0) + 1);
    if (path === "/api/access/status") {
      await route.fulfill({ status: valid ? 200 : 401, contentType: "application/json",
        body: JSON.stringify(valid ? beneficiaryStatus : { detail: "Not authenticated" }) });
      return;
    }
    if (path === "/api/access/session") {
      await route.fulfill({ status: 401, contentType: "application/json",
        body: '{"detail":"Not authenticated"}' });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });

  await page.goto("/recovery");
  await expect(page.getByRole("heading", { name: "Beneficiary recovery" })).toBeVisible();
  await expect(page.getByText("Access verified")).toBeVisible();
  expect(calls.get("/api/auth/me") ?? 0).toBe(0);

  valid = false;
  await page.reload();
  await expect(page).toHaveURL(/\/access\/login$/);
  await expect(page.getByRole("heading", { name: "Beneficiary sign-in" })).toBeVisible();
  expect(calls.get("/api/access/session")).toBe(1);
  expect(calls.get("/api/auth/refresh") ?? 0).toBe(0);
});

test("an owner session cannot authorize the beneficiary recovery route", async ({ page }) => {
  const calls = new Map<string, number>();
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.set(path, (calls.get(path) ?? 0) + 1);
    if (path === "/api/access/status" || path === "/api/access/session") {
      await route.fulfill({ status: 401, contentType: "application/json",
        body: '{"detail":"Not authenticated"}' });
      return;
    }
    const responses: Record<string, object> = {
      "/api/auth/me": { id: 1, email: "owner@example.com" },
      "/api/vault/crypto-material": { material_revision: 1, wrapped_vmk: null },
      "/api/vault/status": { status: "active", armed: false, release_hold: true },
      "/api/vault/readiness": { initialized: false, material_revision: 1,
        ceremony_status: "NONE", quorum_assigned: false, owner_reported_drill: null,
        threshold: 2, total: 3 },
      "/api/heartbeat": { armed: false, last_check_in: null, interval_days: 30, grace_days: 7 },
      "/api/stats": { vault_status: "active", message_count: 0, beneficiary_count: 0 },
    };
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(responses[path] ?? {}) });
  });

  await page.goto("/home");
  await expect(page.getByRole("heading", { name: "Your vault", exact: true })).toBeVisible();
  // Next's patched History API updates the App Router without a document reload.
  await page.evaluate(() => window.history.pushState(null, "", "/recovery"));
  await expect(page).toHaveURL(/\/access\/login$/);
  await expect(page.getByRole("heading", { name: "Beneficiary sign-in" })).toBeVisible();
  expect(calls.get("/api/access/session")).toBe(1);
  expect(calls.get("/api/auth/refresh") ?? 0).toBe(0);
});
