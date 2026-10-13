import { test, expect } from "@playwright/test";
import { requireLiveBackend, requireOk, freshOwner } from "./e2e-guard";
import {writeFileSync} from "node:fs";

// Zero-knowledge golden path: owner encrypts -> beneficiary recovers after
// trigger — AND the network boundary holds throughout: no request body may
// carry the vault passphrase, raw shares, or message plaintext (the login
// password travels only to its three auth endpoints, by design over TLS).
// Requires a live backend (NEXT_PUBLIC_API_URL, default :8000) with a seeded
// owner (E2E_OWNER_EMAIL/PASSWORD). Skips cleanly when unavailable, so plain
// `npx playwright test` stays green without a backend.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
let OWNER_EMAIL = process.env.E2E_OWNER_EMAIL ?? "owner@example.com";
const OWNER_PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "DevPassword123456";
const VAULT_PASSPHRASE = "E2E-Vault-Passphrase-12345";

test.beforeAll(async ({ request }) => {
  await requireLiveBackend(request, "golden-path spec");
  const login = await request
    .post(`${API}/auth/login`, { data: { email: OWNER_EMAIL, password: OWNER_PASSWORD } })
    .catch(() => null);
  await requireOk(login, "golden path needs a seeded owner");
});

test("golden path: encrypt -> trigger -> 2-share recovery -> decrypt", async ({
  page,
  context,
  request,
}) => {
  test.setTimeout(240000);
  OWNER_EMAIL=await freshOwner(request, OWNER_PASSWORD);
  const STAMP = Date.now();
  const MESSAGES = [1, 2, 3].map((i) => ({
    label: `Golden Secret ${i} ${STAMP}`,
    body: `The golden plaintext ${i} ${STAMP}`,
  }));
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
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/home$/);

  // --- Owner: vault setup, capture the 3 shares ---
  await page.goto("/vault/setup");
  // Step 1 is Policy (defaults 2-of-3) -> Continue to the passphrase step.
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Vault passphrase").fill(VAULT_PASSPHRASE);
  await page.getByLabel("Confirm passphrase").fill(VAULT_PASSPHRASE);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Generate vault key" }).click();
  const shares: string[] = [];
  for (const i of [1, 2, 3]) {
    await page.getByRole("button",{name:`Go to share ${i}`,exact:true}).click();
    const el = page.getByTestId(`share-${i}`);
    await expect(el).toBeVisible({ timeout: 30000 });
    shares.push((await el.textContent())?.trim() ?? "");
    await page.getByRole("button",{name:"I\'ve stored this safely",exact:true}).click();
  }
  expect(shares.every((s) => s.length > 10)).toBe(true);
  await page.getByRole("button", { name: "Complete setup" }).click();
  await expect(page).toHaveURL(/\/vault$/);
  await page.getByRole("button",{name:"Unlock vault",exact:true}).click();
  await page.getByLabel("Vault passphrase").fill(VAULT_PASSPHRASE);
  await page.getByRole("button",{name:"Unlock",exact:true}).click();

  // --- Owner: already unlocked post-setup; create three encrypted messages ---
  await expect(page.getByRole("button", { name: "New secret" })).toBeVisible();
  for (const m of MESSAGES) {
    await page.getByRole("button", { name: "New secret" }).click();
    await page.getByLabel("Label").fill(m.label);
    await page.getByLabel("Secret text").fill(m.body);
    await page.getByRole("button", { name: "Encrypt and save" }).click();
    await expect(page.getByText(m.label)).toBeVisible();
  }

  // --- Owner: reload (VMK is memory-only) -> unlock from scratch ---
  await page.reload();
  await page.getByRole("button",{name:"Unlock vault",exact:true}).click();
  await page.getByLabel("Vault passphrase").fill(VAULT_PASSPHRASE);
  await page.getByRole("button", { name: "Unlock" }).click();
  for (const m of MESSAGES) await expect(page.getByText(m.label)).toBeVisible();

  // --- Owner: add + invite beneficiary, capture the link ---
  await page.goto("/beneficiaries");
  await page.getByRole("button",{name:"Add person",exact:true}).click();
  await page.getByLabel("Name").fill(BEN_NAME);
  await page.getByLabel("Email").fill(BEN_EMAIL);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const row = page.locator("li", { hasText: BEN_NAME });
  await row.getByRole("button",{name:"Manage",exact:true}).click();
  await row.getByRole("button", { name: "Invite" }).click();
  const linkEl = page.locator("code", { hasText: "/access/invite#" });
  await expect(linkEl).toBeVisible();
  const link = (await linkEl.textContent())?.trim() ?? "";
  expect(link).toContain("/access/invite#");

  // --- Owner: manual trigger ---
  await page.goto("/heartbeat");
  await page.getByRole("button", { name: /trigger vault/i }).click();
  await page.getByLabel("Login password").fill(OWNER_PASSWORD);
  await page.getByRole("checkbox", { name: /releases access for my trusted people/i }).check();
  await page.getByRole("button", { name: "Trigger now" }).click();
  await expect(page.getByText(/triggered/i).first()).toBeVisible({ timeout: 15000 });

  // --- Beneficiary: accept invite (isolated storage, no owner session) ---
  const benCtx = await context.browser()?.newContext();
  if (!benCtx) {
    if (process.env.CI) throw new Error("no browser for beneficiary context in CI");
    test.skip(true, "no browser for beneficiary context");
  }
  const ben = await benCtx!.newPage();
  tap(ben);
  await ben.goto(link);
  await ben.getByRole("button", { name: "Accept invitation" }).click();
  await expect(ben.getByText(/accepted/i).first()).toBeVisible();
  await ben.goto("/recovery");

  // --- Beneficiary: gate -> shares -> decrypt, plaintext must match ---
  await expect(ben.getByText(/triggered/i).first()).toBeVisible({ timeout: 15000 });
  await ben.getByRole("button", { name: "Continue" }).click();
  await ben.getByLabel("Share 1").fill(shares[0]);
  await ben.getByLabel("Share 2").fill(shares[1]);
  await ben.getByRole("button", { name: "Reconstruct" }).click();
  for (const m of MESSAGES) {
    const msgRow = ben.locator("li", { hasText: m.label });
    await expect(msgRow).toBeVisible({ timeout: 15000 });
    await msgRow.getByRole("button", { name: "Decrypt" }).click();
    await expect(ben.getByText(m.body)).toBeVisible({ timeout: 15000 });
  }

  // --- Boundary assertion: forbidden material in NO request body ---
  const forbidden = [...shares, VAULT_PASSPHRASE, ...MESSAGES.map((m) => m.body)];
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
  // Both role cookies can coexist. Recovery logout revokes only the
  // beneficiary family, even when an owner cookie is present in this browser.
  const ownerLogin=await benCtx!.request.post(`${API}/auth/login`, {data:{email:OWNER_EMAIL,password:OWNER_PASSWORD}});
  expect(ownerLogin.ok()).toBe(true);
  await ben.reload();
  await expect(ben.getByRole("heading",{name:"Beneficiary recovery",exact:true})).toBeVisible();
  await ben.getByRole("button",{name:"Log out",exact:true}).first().click();
  await expect(ben).toHaveURL(/\/access\/login$/);
  expect((await benCtx!.request.get(`${API}/access/status`)).status()).toBe(401);
  expect((await benCtx!.request.get(`${API}/auth/me`)).status()).toBe(200);
  // Explicit out-of-browser custody of SYNTHETIC test shares for the isolated
  // restore rehearsal. No production data or browser storage is used.
  if(process.env.E2E_RESTORE_FIXTURE_PATH) writeFileSync(process.env.E2E_RESTORE_FIXTURE_PATH,JSON.stringify({owner_email:OWNER_EMAIL,beneficiary_email:BEN_EMAIL,shares,labels:MESSAGES.map(m=>m.label),bodies:MESSAGES.map(m=>m.body)}));
  await benCtx!.close();
});
