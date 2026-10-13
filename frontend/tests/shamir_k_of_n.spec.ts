import { test, expect } from "@playwright/test";
import { requireLiveBackend, requireOk, freshOwner } from "./e2e-guard";

// Generalized k-of-n proof: 3-of-5 setup through the UI, then recovery with a
// NON-prefix subset (shares 3,4,5) — the first configuration where the
// generalized ceremony really matters. Skips cleanly without a live backend.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
let OWNER_EMAIL = process.env.E2E_OWNER_EMAIL ?? "owner@example.com";
const OWNER_PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "DevPassword123456";
const VAULT_PASSPHRASE = "E2E-KofN-Passphrase-12345";

test.beforeAll(async ({ request }) => {
  await requireLiveBackend(request, "k-of-n spec");
  const login = await request
    .post(`${API}/auth/login`, { data: { email: OWNER_EMAIL, password: OWNER_PASSWORD } })
    .catch(() => null);
  await requireOk(login, "k-of-n path needs a seeded owner");
});

test("3-of-5: setup -> non-prefix subset recovery -> decrypt", async ({
  page,
  context,
  request,
}) => {
  test.setTimeout(240000);
  OWNER_EMAIL=await freshOwner(request, OWNER_PASSWORD);
  const BODY = `The k-of-n plaintext ${Date.now()}`;
  const LABEL = `KofN Secret ${Date.now()}`;
  const BEN_NAME = `E2E KofN Ben ${Date.now()}`;
  const BEN_EMAIL = `e2e-kofn-ben-${Date.now()}@example.com`;

  await request.post(`${API}/auth/login`, {
    data: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
  });
  await request.post(`${API}/vault/reset-status`, {
    data: { password: OWNER_PASSWORD, confirm: true },
  });

  await page.goto("/");
  await page.getByLabel("Email").fill(OWNER_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/home$/);

  // --- 3-of-5 setup via the policy step ---
  await page.goto("/vault/setup");
  await page.getByLabel("Total shares (n)").selectOption("5");
  await page.getByLabel("Required shares (k)").selectOption("3");
  await expect(page.getByLabel("Required shares (k)")).toHaveValue("3");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Vault passphrase").fill(VAULT_PASSPHRASE);
  await page.getByLabel("Confirm passphrase").fill(VAULT_PASSPHRASE);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Generate vault key" }).click();
  const shares: string[] = [];
  for (const i of [1, 2, 3, 4, 5]) {
    await page.getByRole("button",{name:`Go to share ${i}`,exact:true}).click();
    const el = page.getByTestId(`share-${i}`);
    await expect(el).toBeVisible({ timeout: 30000 });
    shares.push((await el.textContent())?.trim() ?? "");
    await page.getByRole("button",{name:"I\'ve stored this safely",exact:true}).click();
  }
  expect(shares.every((s) => s.startsWith("LLS1-"))).toBe(true);
  await page.getByRole("button", { name: "Complete setup" }).click();
  await expect(page).toHaveURL(/\/vault$/);
  await page.getByRole("button",{name:"Unlock vault",exact:true}).click();
  await page.getByLabel("Vault passphrase").fill(VAULT_PASSPHRASE);
  await page.getByRole("button",{name:"Unlock",exact:true}).click();

  // --- One message, one beneficiary, manual trigger ---
  await page.getByRole("button", { name: "New secret" }).click();
  await page.getByLabel("Label").fill(LABEL);
  await page.getByLabel("Secret text").fill(BODY);
  await page.getByRole("button", { name: "Encrypt and save" }).click();
  await expect(page.getByText(LABEL)).toBeVisible();

  await page.goto("/beneficiaries");
  await page.getByRole("button",{name:"Add person",exact:true}).click();
  await page.getByLabel("Name").fill(BEN_NAME);
  await page.getByLabel("Email").fill(BEN_EMAIL);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const row = page.locator("li", { hasText: BEN_NAME });
  await row.getByRole("button",{name:"Manage",exact:true}).click();
  await row.getByRole("button", { name: "Invite" }).click();
  const link = ((await page.locator("code", { hasText: "/access/invite#" }).textContent())?.trim() ?? "");
  expect(link).toContain("/access/invite#");

  await page.goto("/heartbeat");
  await page.getByRole("button", { name: /trigger vault/i }).click();
  await page.getByLabel("Login password").fill(OWNER_PASSWORD);
  await page.getByRole("checkbox", { name: /releases access for my trusted people/i }).check();
  await page.getByRole("button", { name: "Trigger now" }).click();
  await expect(page.getByText(/triggered/i).first()).toBeVisible({ timeout: 15000 });

  // --- Recover with shares 3,4,5 (indexes 3..5, NOT the first k) ---
  const benCtx = await context.browser()?.newContext();
  if (!benCtx) {
    if (process.env.CI) throw new Error("no browser for beneficiary context in CI");
    test.skip(true, "no browser for beneficiary context");
  }
  const ben = await benCtx!.newPage();
  await ben.goto(link);
  await ben.getByRole("button", { name: "Accept invitation" }).click();
  await expect(ben.getByText(/accepted/i).first()).toBeVisible();
  await ben.goto("/recovery");
  await expect(ben.getByText(/triggered/i).first()).toBeVisible({ timeout: 15000 });
  await ben.getByRole("button", { name: "Continue" }).click();
  await expect(ben.getByText(/Enter 3 of 5 shares/)).toBeVisible({ timeout: 15000 });
  await ben.getByLabel("Share 1").fill(shares[2]);
  await ben.getByLabel("Share 2").fill(shares[3]);
  await ben.getByLabel("Share 3").fill(shares[4]);
  await ben.getByRole("button", { name: "Reconstruct" }).click();
  const msgRow = ben.locator("li", { hasText: LABEL });
  await expect(msgRow).toBeVisible({ timeout: 15000 });
  await msgRow.getByRole("button", { name: "Decrypt" }).click();
  await expect(ben.getByText(BODY)).toBeVisible({ timeout: 15000 });
  await benCtx!.close();
});
