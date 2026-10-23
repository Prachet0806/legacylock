import { defineConfig } from "@playwright/test";

// Browser-independent cryptography/session checks should not need a dev server
// or a live backend. Keep this fast path separate from hosted journey tests.
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/crypto.spec.ts",
  workers: 1,
});
