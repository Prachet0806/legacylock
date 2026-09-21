import { test, expect } from "@playwright/test";

// Automatic dead-man-switch path: owner configures heartbeat -> simulated
// inactivity (non-prod run-check time travel) drives ACTIVE -> GRACE ->
// TRIGGERED with reason=inactivity -> beneficiary recovers, proving the
// automatic release is equivalent to the manual one. No request body may
// carry the vault passphrase, raw shares, or message plaintext.
// Requires a live backend (NEXT_PUBLIC_API_URL, default :8000) with a seeded
// owner (E2E_OWNER_EMAIL/PASSWORD). Skips cleanly when unavailable.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const OWNER_EMAIL = process.env.E2E_OWNER_EMAIL ?? "owner@example.com";
const OWNER_PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "DevPassword123456";
const VAULT_PASSPHRASE = "E2E-Auto-Passphrase-12345";

test.beforeAll(async ({ request }) => {
  const health = await request.get(`${API}/health`).catch(() => null);
  test.skip(!health || !health.ok(), "auto-trigger path needs a live backend");
  const login = await request
    .post(`${API}/auth/login`, { data: { email: OWNER_EMAIL, password: OWNER_PASSWORD } })
    .catch(() => null);
  test.skip(!login || !login.ok(), "auto-trigger path needs a seeded owner (seed_dev_user.py)");
});

test("auto path: heartbeat 30/7 -> grace -> checkin cancels -> triggered -> recovery", async ({
  page,
  context,
  request,
}) => {
  test.setTimeout(240000);
  const BODY = `The auto plaintext ${Date.now()}`;
  const LABEL = `Auto Secret ${Date.now()}`;
  const BEN_NAME = `E2E Auto Ben ${Date.now()}`;
  const BEN_EMAIL = `e2e-auto-ben-${Date.now()}@example.com`;

  // Reset to ACTIVE first so reruns against a used DB still work.
  await request.post(`${API}/auth/login`, {
    data: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
  });
  await request.post(`${API}/vault/reset-status`, {
    data: { password: OWNER_PASSWORD, confirm: true },
  });

  const bodies: Array<{ url: string; body: string }> = [];
  const tap = (p: typeof page) =>
    p.on("request", (req) => {
      if (["POST", "PUT", "PATCH"].includes(req.method())) {
        bodies.push({ url: req.url(), body: req.postData() ?? "" });
      }
    });
  tap(page);

  // --- Owner: login ---
  await page.goto("/");
  await page.getByLabel("Email").fill(OWNER_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/home$/);

  // --- Owner: vault setup, capture 3 shares (default 2-of-3) ---
  await page.goto("/vault/setup");
  // Step 1 is Policy (defaults 2-of-3) -> Continue to the passphrase step.
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Vault passphrase").fill(VAULT_PASSPHRASE);
  await page.getByLabel("Confirm passphrase").fill(VAULT_PASSPHRASE);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Generate vault key" }).click();
  const shares: string[] = [];
  for (const i of [1, 2, 3]) {
    const el = page.getByTestId(`share-${i}`);
    await expect(el).toBeVisible({ timeout: 30000 });
    shares.push((await el.textContent())?.trim() ?? "");
  }
  expect(shares.every((s) => s.length > 10)).toBe(true);
  for (const i of [1, 2, 3]) {
    await page.getByRole("checkbox", { name: new RegExp(`share ${i}`, "i") }).check();
  }
  await page.getByRole("button", { name: /finish/i }).click();
  await expect(page).toHaveURL(/\/vault$/);

  // --- Owner: one encrypted message ---
  await expect(page.getByRole("button", { name: "New message" })).toBeVisible();
  await page.getByRole("button", { name: "New message" }).click();
  await page.getByLabel("Label").fill(LABEL);
  await page.getByLabel("Secret text").fill(BODY);
  await page.getByRole("button", { name: "Encrypt and save" }).click();
  await expect(page.getByText(LABEL)).toBeVisible();

  // --- Owner: heartbeat 30/7 via UI, check in ---
  await page.goto("/heartbeat");
  await page.getByLabel("Check-in every (days)").fill("30");
  await page.getByLabel("Grace period (days)").fill("7");
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByText("Currently: every 30 days, 7 days grace.")).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole("button", { name: "Check in now" }).click();
  await expect(page.getByText("ACTIVE").first()).toBeVisible({ timeout: 15000 });

  // --- Owner: add + invite beneficiary BEFORE the trigger ---
  await page.goto("/beneficiaries");
  await page.getByLabel("Name").fill(BEN_NAME);
  await page.getByLabel("Email").fill(BEN_EMAIL);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const row = page.locator("li", { hasText: BEN_NAME });
  await row.getByRole("button", { name: "Invite" }).click();
  const linkEl = page.locator("code", { hasText: "/access/invite/" });
  await expect(linkEl).toBeVisible();
  const link = (await linkEl.textContent())?.trim() ?? "";
  expect(link).toContain("/access/invite/");

  // --- Time travel +31d: ACTIVE -> GRACE ---
  const grace = await request.post(`${API}/heartbeat/run-check`, {
    data: { advance_days: 31 },
  });
  expect(grace.ok()).toBe(true);
  expect(await grace.json().then((b) => b.actions.join(","))).toContain("grace_started");
  await page.goto("/heartbeat");
  await expect(page.getByText("GRACE").first()).toBeVisible({ timeout: 15000 });

  // --- Check-in cancels grace -> ACTIVE ---
  await page.getByRole("button", { name: "Check in now" }).click();
  await expect(page.getByText("ACTIVE").first()).toBeVisible({ timeout: 15000 });

  // --- Time travel +31d then +40d: GRACE -> TRIGGERED (inactivity) ---
  const grace2 = await request.post(`${API}/heartbeat/run-check`, {
    data: { advance_days: 31 },
  });
  expect(await grace2.json().then((b) => b.actions.join(","))).toContain("grace_started");
  const trig = await request.post(`${API}/heartbeat/run-check`, {
    data: { advance_days: 40 },
  });
  expect(trig.ok()).toBe(true);
  expect(await trig.json().then((b) => b.actions.join(","))).toContain("triggered");
  await page.goto("/heartbeat");
  await expect(page.getByText("TRIGGERED").first()).toBeVisible({ timeout: 15000 });

  // --- Idempotent re-run: still triggered, no new actions ---
  const again = await request.post(`${API}/heartbeat/run-check`, {
    data: { advance_days: 40 },
  });
  expect(await again.json().then((b) => b.actions)).toEqual([]);

  // --- Beneficiary: accept invite, gate shows triggered, recover ---
  const benCtx = await context.browser()?.newContext();
  test.skip(!benCtx, "no browser for beneficiary context");
  const ben = await benCtx!.newPage();
  tap(ben);
  await ben.goto(link);
  await ben.getByRole("button", { name: "Accept invitation" }).click();
  await expect(ben.getByText(/accepted/i).first()).toBeVisible();
  await ben.goto("/recovery");
  await expect(ben.getByText(/triggered/i).first()).toBeVisible({ timeout: 15000 });
  await ben.getByRole("button", { name: "Continue" }).click();
  await ben.getByLabel("Share 1").fill(shares[0]);
  await ben.getByLabel("Share 2").fill(shares[1]);
  await ben.getByRole("button", { name: "Submit shares" }).click();
  const msgRow = ben.locator("li", { hasText: LABEL });
  await expect(msgRow).toBeVisible({ timeout: 15000 });
  await msgRow.getByRole("button", { name: "Decrypt" }).click();
  await expect(ben.getByText(BODY)).toBeVisible({ timeout: 15000 });

  // --- Boundary assertion: forbidden material in NO request body ---
  const forbidden = [...shares, VAULT_PASSPHRASE, BODY];
  const passwordEndpoints = ["/auth/login", "/vault/trigger", "/vault/reset-status"];
  expect(bodies.length).toBeGreaterThan(0);
  for (const { url, body } of bodies) {
    for (const secret of forbidden) {
      expect(body, `${url} leaked forbidden material`).not.toContain(secret);
    }
    if (body.includes(OWNER_PASSWORD)) {
      expect(
        passwordEndpoints.some((p) => url.includes(p)),
        `${url} carried the login password outside auth endpoints`,
      ).toBe(true);
    }
  }
  await benCtx!.close();
});
