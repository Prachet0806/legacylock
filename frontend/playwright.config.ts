import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  // Stateful specs (golden path, auto-trigger) share a single seeded owner
  // vault, so files must not run concurrently against the same backend.
  workers: 1,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
  },
  // Serve the app automatically so `npx playwright test` works with no
  // manual `npm run dev`. Reuses your dev server locally when one is up.
  // NEXT_PUBLIC_API_URL is forwarded so the dev server targets the E2E backend.
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 180000,
    env: {
      NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
    },
  },
});
