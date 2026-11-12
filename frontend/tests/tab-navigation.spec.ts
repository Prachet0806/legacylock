import { expect, test } from "@playwright/test";

test("owner tab changes keep the shell visible without another auth probe", async ({ page }) => {
  const calls = new Map<string, number>();
  let holdPeople = false;
  let releasePeople: (() => void) | undefined;
  const peopleGate = new Promise<void>((resolve) => { releasePeople = resolve; });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.set(path, (calls.get(path) ?? 0) + 1);
    if (path === "/api/beneficiaries" && holdPeople) await peopleGate;
    const responses: Record<string, object> = {
      "/api/auth/me": { id: 1, email: "owner@example.com" },
      "/api/vault/crypto-material": { material_revision: 0, wrapped_vmk: null },
      "/api/vault/status": { status: "active", armed: false, release_hold: true },
      "/api/vault/readiness": {
        initialized: false, material_revision: 0, ceremony_status: "NONE",
        quorum_assigned: false, owner_reported_drill: null, threshold: 2, total: 3,
      },
      "/api/heartbeat": { armed: false, last_check_in: null, interval_days: 30, grace_days: 7 },
      "/api/stats": { vault_status: "active", message_count: 0, beneficiary_count: 0 },
      "/api/beneficiaries": [],
      "/api/vault/recovery-policy": { recovery_threshold: 2, recovery_total: 3 },
      "/api/scheduler-health": { status: "ok" },
    };
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify(responses[path] ?? {}),
    });
  });

  try {
    await page.goto("/home");
    await expect(page.getByRole("heading", { name: "Your vault" })).toBeVisible();
    await expect.poll(() => calls.get("/api/vault/readiness") ?? 0).toBeGreaterThan(0);
    const meBefore = calls.get("/api/auth/me") ?? 0;
    const materialBefore = calls.get("/api/vault/crypto-material") ?? 0;
    const readinessBefore = calls.get("/api/vault/readiness") ?? 0;

    holdPeople = true;
    await page.getByRole("link", { name: "People", exact: true }).click();
    await expect(page).toHaveURL(/\/beneficiaries$/);
    await expect(page.getByRole("heading", { name: "People" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Home" })).toBeVisible();
    await expect(page.getByText("Checking session…")).toHaveCount(0);
    await expect(page.getByLabel("Loading trusted people")).toBeVisible();

    releasePeople?.();
    await expect(page.getByLabel("Loading trusted people")).toHaveCount(0);
    expect(calls.get("/api/auth/me") ?? 0).toBe(meBefore);
    expect(calls.get("/api/vault/crypto-material") ?? 0).toBe(materialBefore);
    expect(calls.get("/api/vault/readiness") ?? 0).toBe(readinessBefore + 1);

    const statusBefore = calls.get("/api/vault/status") ?? 0;
    const heartbeatBefore = calls.get("/api/heartbeat") ?? 0;
    const readinessAfterPeople = calls.get("/api/vault/readiness") ?? 0;
    await page.getByRole("link", { name: "Heartbeat", exact: true }).click();
    await expect(page).toHaveURL(/\/heartbeat$/);
    await expect(page.getByRole("heading", { name: "Set up your vault first" })).toBeVisible();
    expect(calls.get("/api/vault/status") ?? 0).toBe(statusBefore + 1);
    expect(calls.get("/api/heartbeat") ?? 0).toBe(heartbeatBefore + 1);
    expect(calls.get("/api/vault/readiness") ?? 0).toBe(readinessAfterPeople + 1);
    expect(calls.get("/api/auth/me") ?? 0).toBe(meBefore);

    await page.evaluate(() => window.dispatchEvent(new Event("legacylock-session-changed")));
    await expect.poll(() => calls.get("/api/auth/me") ?? 0).toBe(meBefore + 1);
    await page.evaluate(() => window.dispatchEvent(
      new CustomEvent("legacylock-session-expired", { detail: "owner" }),
    ));
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: "Sign in to your vault" })).toBeVisible();
  } finally {
    releasePeople?.();
  }
});
