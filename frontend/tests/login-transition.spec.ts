import { expect, test } from "@playwright/test";

test("successful login shows an opening state until the dashboard is ready", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  let releaseMe: (() => void) | undefined;
  const meGate = new Promise<void>((resolve) => { releaseMe = resolve; });
  let loggedIn = false;

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/login") {
      loggedIn = true;
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      return;
    }
    if (path === "/api/auth/me") {
      if (!loggedIn) {
        await route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"Not authenticated"}' });
        return;
      }
      await meGate;
      await route.fulfill({ status: 200, contentType: "application/json", body: '{"id":1,"email":"owner@example.com"}' });
      return;
    }
    if (path === "/api/auth/refresh") {
      await route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"Not authenticated"}' });
      return;
    }
    const body = JSON.stringify(({
      "/api/vault/crypto-material": { material_revision: 0 },
      "/api/vault/status": { status: "active", armed: false },
      "/api/stats": { vault_status: "active", message_count: 0, beneficiary_count: 0 },
      "/api/heartbeat": { armed: false, last_check_in: null },
      "/api/vault/readiness": { initialized: false, ceremony_status: "NONE", quorum_assigned: false, owner_reported_drill: null, eligible_assignments: 0, total: 0 },
    } as Record<string, object>)[path] ?? {});
    await route.fulfill({ status: 200, contentType: "application/json", body });
  });

  try {
    await page.goto("/");
    await page.getByLabel("Email").fill("owner@example.com");
    await page.getByLabel("Password", { exact: true }).fill("example-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    await expect(page).toHaveURL(/\/home$/);
    await expect(page.getByRole("status").getByText("Opening your vault…", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sign in to your vault" })).toHaveCount(0);

    releaseMe?.();
    await expect(page.getByRole("heading", { name: "Your vault", exact: true })).toBeVisible();
    expect(pageErrors).toEqual([]);
  } finally {
    releaseMe?.();
  }
});

test("a second tab opened at the bare site URL resumes the owner session", async ({ context }) => {
  const origin = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
  await context.addCookies([{ name: "legacylock_owner_session", value: "fixture", url: origin }]);
  await context.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const authenticated = route.request().headers().cookie?.includes("legacylock_owner_session=fixture");
    if (path === "/api/auth/me" && !authenticated) {
      await route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"Not authenticated"}' });
      return;
    }
    const responses: Record<string, object> = {
      "/api/auth/me": { id: 1, email: "owner@example.com" },
      "/api/vault/crypto-material": { material_revision: 0, wrapped_vmk: null },
      "/api/vault/status": { status: "active", armed: false, release_hold: true },
      "/api/vault/readiness": { initialized: false, material_revision: 0, ceremony_status: "NONE", quorum_assigned: false, owner_reported_drill: null },
      "/api/heartbeat": { armed: false, last_check_in: null, interval_days: 30, grace_days: 7 },
      "/api/stats": { vault_status: "active", message_count: 0, beneficiary_count: 0 },
    };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(responses[path] ?? {}) });
  });

  const first = await context.newPage();
  await first.goto(`${origin}/home`);
  await expect(first.getByRole("heading", { name: "Your vault", exact: true })).toBeVisible();

  const second = await context.newPage();
  await second.goto(origin);
  await expect(second).toHaveURL(/\/home$/);
  await expect(second.getByRole("heading", { name: "Your vault", exact: true })).toBeVisible();
  await expect(first).toHaveURL(/\/home$/);
});

test("bare entry can refresh an owner session without broadcasting expiry", async ({ page }) => {
  let accessValid = false;
  let refreshes = 0;
  await page.addInitScript(() => {
    window.addEventListener("legacylock-session-expired", () => {
      sessionStorage.setItem("unexpected-expiry", "true");
    });
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") {
      await route.fulfill({
        status: accessValid ? 200 : 401, contentType: "application/json",
        body: accessValid ? '{"id":1,"email":"owner@example.com"}' : '{"detail":"Not authenticated"}',
      });
      return;
    }
    if (path === "/api/auth/refresh") {
      refreshes++;
      accessValid = true;
    }
    const responses: Record<string, object> = {
      "/api/vault/crypto-material": { material_revision: 0, wrapped_vmk: null },
      "/api/vault/status": { status: "active", armed: false, release_hold: true },
      "/api/vault/readiness": { initialized: false, material_revision: 0, ceremony_status: "NONE", quorum_assigned: false, owner_reported_drill: null },
      "/api/heartbeat": { armed: false, last_check_in: null, interval_days: 30, grace_days: 7 },
      "/api/stats": { vault_status: "active", message_count: 0, beneficiary_count: 0 },
    };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(responses[path] ?? {}) });
  });

  await page.goto("/");
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("heading", { name: "Your vault", exact: true })).toBeVisible();
  expect(refreshes).toBe(1);
  expect(await page.evaluate(() => sessionStorage.getItem("unexpected-expiry"))).toBeNull();
});

test("anonymous bare entry does not broadcast an owner expiry", async ({ page }) => {
  let refreshes = 0;
  await page.addInitScript(() => {
    window.addEventListener("legacylock-session-expired", () => {
      sessionStorage.setItem("unexpected-expiry", "true");
    });
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/refresh") refreshes++;
    await route.fulfill({
      status: 401, contentType: "application/json", body: '{"detail":"Not authenticated"}',
    });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to your vault" })).toBeVisible();
  await expect.poll(() => refreshes).toBe(1);
  expect(await page.evaluate(() => sessionStorage.getItem("unexpected-expiry"))).toBeNull();
  await expect(page).toHaveURL(/\/$/);
});
