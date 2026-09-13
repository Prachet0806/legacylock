import { test, expect } from "@playwright/test";

// Zero-knowledge golden path: owner encrypts -> beneficiary recovers after
// trigger — AND the network boundary holds throughout: no request body may
// carry the vault passphrase, raw shares, or message plaintext (the login
// password travels only to its three auth endpoints, by design over TLS).
// Requires a live backend (NEXT_PUBLIC_API_URL, default :8000) with a seeded
// owner (E2E_OWNER_EMAIL/PASSWORD). Skips cleanly when unavailable, so plain
// `npx playwright test` stays green without a backend.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const OWNER_EMAIL = process.env.E2E_OWNER_EMAIL ?? "owner@example.com";
const OWNER_PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "DevPassword123456";
const VAULT_PASSPHRASE = "E2E-Vault-Passphrase-12345";

test.beforeAll(async ({ request }) => {
  const health = await request.get(`${API}/health`).catch(() => null);
  test.skip(!health || !health.ok(), "golden path needs a live backend");
  const login = await request
    .post(`${API}/auth/login`, { data: { email: OWNER_EMAIL, password: OWNER_PASSWORD } })
    .catch(() => null);
  test.skip(!login || !login.ok(), "golden path needs a seeded owner (seed_dev_user.py)");
});

test("golden path: encrypt -> trigger -> 2-share recovery -> decrypt", async ({
  page,
  context,
  request,
}) => {
  test.setTimeout(180000);
  const BODY = `The golden plaintext ${Date.now()}`;
  const LABEL = `Golden Secret ${Date.now()}`;
  const BEN_NAME = `E2E Ben ${Date.now()}`;
  const BEN_EMAIL = `e2e-ben-${Date.now()}@example.com`;

  // Reset to ACTIVE first so reruns against a used DB still work.
  // Cookie flow: login sets HttpOnly cookies on the shared request context.
  await request.post(`${API}/auth/login`, {
    data: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
  });
  await request.post(`${API}/vault/reset-status`, {
    data: { password: OWNER_PASSWORD, confirm: true },
  });

  // Capture every request body on both sessions for the boundary assertion.
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

  // --- Owner: vault setup, capture the 3 shares ---
  await page.goto("/vault/setup");
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

  // --- Owner: already unlocked post-setup; create one encrypted message ---
  await expect(page.getByRole("button", { name: "New message" })).toBeVisible();
  await page.getByRole("button", { name: "New message" }).click();
  await page.getByLabel("Label").fill(LABEL);
  await page.getByLabel("Secret text").fill(BODY);
  await page.getByRole("button", { name: "Encrypt and save" }).click();
  await expect(page.getByText(LABEL)).toBeVisible();

  // --- Owner: reload (VMK is memory-only) -> unlock from scratch ---
  await page.reload();
  await page.getByLabel("Vault passphrase").fill(VAULT_PASSPHRASE);
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByText(LABEL)).toBeVisible();

  // --- Owner: add + invite beneficiary, capture the link ---
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

  // --- Owner: manual trigger ---
  await page.goto("/heartbeat");
  await page.getByRole("button", { name: /trigger vault/i }).click();
  await page.getByLabel("Login password").fill(OWNER_PASSWORD);
  await page.getByRole("checkbox", { name: /releases beneficiary access/i }).check();
  await page.getByRole("button", { name: "Trigger now" }).click();
  await expect(page.getByText(/triggered/i).first()).toBeVisible({ timeout: 15000 });

  // --- Beneficiary: accept invite (isolated storage, no owner session) ---
  const benCtx = await context.browser()?.newContext();
  test.skip(!benCtx, "no browser for beneficiary context");
  const ben = await benCtx!.newPage();
  tap(ben);
  await ben.goto(link);
  await ben.getByRole("button", { name: "Accept invitation" }).click();
  await expect(ben.getByText(/accepted/i).first()).toBeVisible();
  await ben.goto("/recovery");

  // --- Beneficiary: gate -> shares -> decrypt, plaintext must match ---
  await expect(ben.getByText(/triggered/i).first()).toBeVisible({ timeout: 15000 });
  await ben.getByRole("button", { name: "Continue" }).click();
  await ben.getByLabel("Share A").fill(shares[0]);
  await ben.getByLabel("Share B").fill(shares[1]);
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
