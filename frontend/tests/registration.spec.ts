import { test, expect } from "@playwright/test";
import { requireLiveBackend, requireOk } from "./e2e-guard";

// Gated registration + email verification UI path. Uses the non-production
// test-issue-verification endpoint as the mailbox (the raw token is
// hash-only server-side and otherwise unrecoverable). Skips cleanly without
// a live backend configured with REGISTRATION_INVITE_CODE.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const INVITE_CODE = process.env.E2E_INVITE_CODE ?? "test-invite-code-123";

test.beforeAll(async ({ request }) => {
  await requireLiveBackend(request, "registration spec");
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
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm password").fill(PASSWORD);
  await page.getByLabel("Invitation code").fill("wrong-code-000");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Invalid invitation code")).toBeVisible({ timeout: 15000 });

  // --- Register with the bootstrap code ---
  await page.getByLabel("Invitation code").fill(INVITE_CODE);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible({timeout:15000});

  // --- Negative: login before verification is blocked ---
  await page.goto("/");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/not verified|verify/i).first()).toBeVisible({ timeout: 15000 });

  // --- Verify via the test mailbox endpoint ---
  const issue = await request.post(`${API}/auth/test-issue-verification`, {
    data: { email: EMAIL },
  });
  // A backend without the invite code configured fails closed at register.
  await requireOk(issue, "backend has no REGISTRATION_INVITE_CODE configured");
  const link = ((await issue.json()) as { link: string }).link;
  const token = new URLSearchParams(new URL(link).hash.slice(1)).get("token") ?? "";
  expect(token.length).toBeGreaterThan(10);
  await page.goto(`/verify-email#token=${token}`);
  await page.getByRole("button",{name:"Confirm email verification"}).click();
  await expect(page.getByText("Verified. You can now log in.")).toBeVisible({ timeout: 15000 });
  // Credential must be scrubbed from the URL after use.
  await expect.poll(() => page.url(), { timeout: 15000 }).not.toContain("token=");

  // --- Login now works ---
  await page.goto("/");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("heading", { name: "Set up your vault" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Start vault setup" })).toBeVisible();

  const statContrast = () => page.locator(".stat-tile").first().evaluate((tile) => {
    const channels = (color: string) => (color.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
    const luminance = (color: string) => {
      const [r, g, b] = channels(color).map((value) => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const background = luminance(getComputedStyle(tile).backgroundColor);
    const figure = luminance(getComputedStyle(tile.firstElementChild!).color);
    return (Math.max(background, figure) + 0.05) / (Math.min(background, figure) + 0.05);
  });
  expect(await statContrast()).toBeGreaterThanOrEqual(4.5);
  await page.getByLabel("Switch to light mode").click();
  expect(await statContrast()).toBeGreaterThanOrEqual(4.5);

  // First-time setup belongs to the authenticated dashboard. The owner's
  // Recovery navigation must stay in the owner journey.
  await page.getByRole("navigation", { name: "Recovery" }).getByRole("link", { name: "Recovery readiness" }).click();
  await expect(page).toHaveURL(/\/settings\/security$/);
  await expect(page.getByRole("heading", { name: "Recovery readiness" })).toBeVisible();
  await page.getByRole("link", { name: "Overview" }).click();
  await page.getByRole("link", { name: "Start vault setup" }).click();
  await expect(page).toHaveURL(/\/vault\/setup$/);
  await expect(page.getByRole("heading", { name: "Choose your recovery policy" })).toBeVisible();

  await page.setViewportSize({ width: 320, height: 720 });
  await page.getByRole("button", { name: "Open account menu" }).click();
  await expect(page.getByRole("link", { name: "Settings" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test("resend verification gives an unknown address a generic success", async ({ request }) => {
  const resend = await request.post(`${API}/auth/resend-verification`, {
    data: { email: `nobody-${Date.now()}@example.com` },
  });
  expect(resend.status(), await resend.text()).toBe(200);
  expect((await resend.json()).message).toBe("If the account needs verification, an email has been sent");
});
