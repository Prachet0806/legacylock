import { test, expect } from "@playwright/test";

// Same-origin /api prefix regression: refresh cookies must be scoped Path=/ so
// they survive the edge strip-prefix (browser sees /api/auth/refresh, not
// /auth/refresh). Posts explicitly to /api/* through the dev-server rewrite
// (mirrors production edge behavior), so this spec validates the fix in any
// NEXT_PUBLIC_API_URL mode. Requires a live backend + seeded owner; skips
// cleanly when unavailable.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const OWNER_EMAIL = process.env.E2E_OWNER_EMAIL ?? "owner@example.com";
const OWNER_PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "DevPassword123456";
const BEN_NAME = `Prefix Ben ${Date.now()}`;
const BEN_EMAIL = `prefix-ben-${Date.now()}@example.com`;

test.beforeAll(async ({ request }) => {
  const health = await request.get(`${API}/health`).catch(() => null);
  test.skip(!health || !health.ok(), "prefix spec needs a live backend");
  const login = await request
    .post(`${API}/auth/login`, { data: { email: OWNER_EMAIL, password: OWNER_PASSWORD } })
    .catch(() => null);
  test.skip(!login || !login.ok(), "prefix spec needs a seeded owner (seed_dev_user.py)");
});

test("owner refresh cookie survives the /api prefix", async ({ page, request }) => {
  await request.post(`${API}/auth/login`, {
    data: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
  });
  await request.post(`${API}/vault/reset-status`, {
    data: { password: OWNER_PASSWORD, confirm: true },
  });

  await page.goto("/");
  await page.getByLabel("Email").fill(OWNER_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/home$/);

  // Through the prefix: dev rewrite strips /api, backend sees /auth/refresh.
  // With the old Path=/auth scoping the browser would withhold the cookie -> 401.
  const r = await page.request.post("/api/auth/refresh");
  expect(r.ok()).toBe(true);
});

test("beneficiary refresh cookie survives the /api prefix", async ({ page, request }) => {
  await request.post(`${API}/auth/login`, {
    data: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
  });

  await page.goto("/");
  await page.getByLabel("Email").fill(OWNER_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/home$/);

  await page.goto("/beneficiaries");
  await page.getByLabel("Name").fill(BEN_NAME);
  await page.getByLabel("Email").fill(BEN_EMAIL);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const row = page.locator("li", { hasText: BEN_NAME });
  await row.getByRole("button", { name: "Invite" }).click();
  const linkEl = page.locator("code", { hasText: "/access/invite/" });
  await expect(linkEl).toBeVisible();
  const link = (await linkEl.textContent())?.trim() ?? "";

  const benCtx = await page.context().browser()?.newContext();
  test.skip(!benCtx, "no browser for beneficiary context");
  const ben = await benCtx!.newPage();
  await ben.goto(link);
  await ben.getByRole("button", { name: "Accept invitation" }).click();
  await expect(ben.getByText(/accepted/i).first()).toBeVisible();

  // Through the prefix: backend sees /access/session. Old Path=/access -> 401.
  const r = await ben.request.post("/api/access/session");
  expect(r.ok()).toBe(true);
  await benCtx!.close();
});
