import { defineConfig } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const port = new URL(baseURL).port || "3000";

export default defineConfig({
  testDir: "./tests",
  // Stateful specs (golden path, auto-trigger) share a single seeded owner
  // vault, so files must not run concurrently against the same backend.
  workers: 1,
  use: {
    baseURL,
  },
  // Serve the app automatically so `npx playwright test` works with no
  // manual `npm run dev`. Reuses your dev server locally when one is up.
  // NEXT_PUBLIC_API_URL is forwarded so the dev server targets the E2E backend.
  webServer: {
    command: process.env.E2E_PRODUCTION === "1" ? "node scripts/standalone.cjs" : `node node_modules/next/dist/bin/next dev -p ${port}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 180000,
    env: {
      NEXT_PUBLIC_API_URL: "/api",
      API_UPSTREAM: process.env.API_UPSTREAM ?? "http://localhost:8000",
      PORT: port,
    },
  },
});
