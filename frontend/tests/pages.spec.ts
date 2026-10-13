import { test, expect } from "@playwright/test";

for(const [path,confirmation] of [["/access/login","Confirm sign-in"],["/access/invite","Accept invitation"],["/verify-email","Confirm email verification"]]) {
  test(`${path} handles an incoming fragment while already open, without consuming it through GET`,async({page})=>{
    let consumes=0;
    page.on("request",req=>{if(req.method()==="POST")consumes++;});
    await page.goto(path);
    await expect(page.locator("main")).toHaveAttribute("data-credential-ready","true");
    await page.goto(`${path}#token=synthetic-scanner-safe-capability-12345`);
    await expect(page.getByRole("button",{name:confirmation,exact:true})).toBeEnabled();
    await expect.poll(()=>new URL(page.url()).hash).toBe("");
    expect(consumes).toBe(0);
  });
}

// Public routes render without a session.
test("/ renders login", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Owner login" })).toBeVisible();
});

test("production CSP uses fresh nonces, permits hydration and blocks an unapproved inline script", async ({ page }) => {
  test.skip(process.env.E2E_PRODUCTION !== "1", "Production nonce contract");
  // Inject into parser-delivered HTML. strict-dynamic intentionally trusts
  // non-parser scripts inserted by a trusted script, including DevTools eval.
  await page.route((url) => url.pathname === "/", async (route) => {
    const upstream = await route.fetch();
    const html = (await upstream.text()).replace("<head>", "<head><script>window.__unapprovedScriptRan=true</script>");
    await route.fulfill({response:upstream,body:html});
  });
  const response=await page.goto("/");
  const policy=response!.headers()["content-security-policy"];
  const nonce=policy.match(/'nonce-([^']+)'/)?.[1];
  expect(nonce).toBeTruthy();
  expect(policy).not.toContain("'unsafe-eval'");
  expect(response!.headers()["cache-control"]).toContain("no-store");
  expect(response!.headers()["referrer-policy"]).toBe("no-referrer");
  await page.getByLabel("Email").fill("hydration@example.com");
  await expect(page.getByLabel("Email")).toHaveValue("hydration@example.com");
  expect(await page.evaluate(() => (window as typeof window & {__unapprovedScriptRan?:boolean}).__unapprovedScriptRan)).toBeUndefined();
  const refreshed=await page.reload();
  expect(refreshed!.headers()["content-security-policy"]).not.toContain(`'nonce-${nonce}'`);
});

test("/access/invite/[hash] renders", async ({ page }) => {
  await page.goto("/access/invite/deadbeef");
  await expect(page.getByRole("heading", { name: "Beneficiary invitation" })).toBeVisible();
});

// Protected routes bounce logged-out visitors to / (login). Generous timeout:
// the guard probes getMe() then (on /recovery) getAccessStatus(), and dev
// cold-compile adds seconds on first hit.
const PROTECTED = ["/home", "/vault", "/vault/setup", "/beneficiaries", "/heartbeat", "/recovery", "/settings"];

for (const path of PROTECTED) {
  test(`${path} redirects logged-out visitors to /`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveURL(path === "/recovery" ? /\/access\/login$/ : /\/$/, { timeout: 15000 });
    await expect(page.getByRole("heading", { name: path === "/recovery" ? "Beneficiary sign-in" : "Owner login" })).toBeVisible();
  });
}

test("/login redirects to /", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Owner login" })).toBeVisible();
});

test("stale sessionStorage token does NOT admit /recovery", async ({ page }) => {
  // Regression: the shell must not guess beneficiary status from storage.
  // Admission requires a live beneficiary session (proven by golden.spec.ts).
  await page.addInitScript(() => {
    sessionStorage.setItem("legacylock_beneficiary_token", "test-token");
  });
  await page.goto("/recovery");
  await expect(page).toHaveURL(/\/access\/login$/, { timeout: 15000 });
  await expect(page.getByRole("heading", { name: "Beneficiary sign-in" })).toBeVisible();
});
