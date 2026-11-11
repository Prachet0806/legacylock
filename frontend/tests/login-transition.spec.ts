import { expect, test } from "@playwright/test";

test("successful login shows an opening state until the dashboard is ready", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  let releaseMe: (() => void) | undefined;
  const meGate = new Promise<void>((resolve) => { releaseMe = resolve; });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") {
      await meGate;
      await route.fulfill({ status: 200, contentType: "application/json", body: '{"id":1,"email":"owner@example.com"}' });
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
    await expect(page.getByRole("heading", { name: "Your vault" })).toBeVisible();
    expect(pageErrors).toEqual([]);
  } finally {
    releaseMe?.();
  }
});
