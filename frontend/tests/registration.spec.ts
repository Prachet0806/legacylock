import { test, expect } from "@playwright/test";

// Gated registration + email verification UI path. Uses the non-production
// test-issue-verification endpoint as the mailbox (the raw token is
// hash-only server-side and otherwise unrecoverable). Skips cleanly without
// a live backend configured with REGISTRATION_INVITE_CODE.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const INVITE_CODE = process.env.E2E_INVITE_CODE ?? "test-invite-code-123";

test.beforeAll(async ({ request }) => {
  const health = await request.get(`${API}/health`).catch(() => null);
  test.skip(!health || !health.ok(), "registration spec needs a live backend");
});

test("register -> verify -> login; wrong code rejected; pre-verify login blocked", async ({
  page,
  request,
}) => {
  test.setTimeout(180000);
  const STAMP = Date.now();
  const EMAIL = `e2e-reg-${STAMP}@example.com`;
  const PASSWORD = `RegPass12345678-${STAMP}`;

  // --- Negative: wrong invite code ---
  await page.goto("/register");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password (12+ characters)").fill(PASSWORD);
  await page.getByLabel("Confirm password").fill(PASSWORD);
  await page.getByLabel("Invite code").fill("wrong-code-000");
  await page.getByRole("button", { name: "Register" }).click();
  await expect(page.getByText("Invalid invitation code")).toBeVisible({ timeout: 15000 });

  // --- Register with the bootstrap code ---
  await page.getByLabel("Invite code").fill(INVITE_CODE);
  await page.getByRole("button", { name: "Register" }).click();
  await expect(page.getByText("Check your inbox for the verification link")).toBeVisible({
    timeout: 15000,
  });

  // --- Negative: login before verification is blocked ---
  await page.goto("/");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText(/not verified|verify/i).first()).toBeVisible({ timeout: 15000 });

  // --- Verify via the test mailbox endpoint ---
  const issue = await request.post(`${API}/auth/test-issue-verification`, {
    data: { email: EMAIL },
  });
  // A backend without the invite code configured fails closed at register;
  // skip (don't fail) so plain `npx playwright test` stays green there.
  test.skip(!issue.ok(), "backend has no REGISTRATION_INVITE_CODE configured");
  const link = ((await issue.json()) as { link: string }).link;
  const token = new URL(link).searchParams.get("token") ?? "";
  expect(token.length).toBeGreaterThan(10);
  await page.goto(`/verify-email?token=${token}`);
  await expect(page.getByText("Verified. You can now log in.")).toBeVisible({ timeout: 15000 });
  // Credential must be scrubbed from the URL after use.
  await expect.poll(() => page.url(), { timeout: 15000 }).not.toContain("token=");

  // --- Login now works ---
  await page.goto("/");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/home$/);

  // --- Resend cooldown is enumeration-safe (generic success, still unverified n/a) ---
  const resend = await request.post(`${API}/auth/resend-verification`, {
    data: { email: `nobody-${STAMP}@example.com` },
  });
  expect(resend.ok()).toBe(true);
});
