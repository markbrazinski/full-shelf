import { defineConfig } from "@playwright/test";

/**
 * Verify a DEPLOYED replay — the built bundle served by the real
 * deployment transport — rather than the Vite dev server.
 *
 * Same adversarial suite, different target: set FS_BASE_URL to the
 * public URL (or a local container) and the judge-safety spec runs
 * against it, so what ships is what was proven.
 *
 *   FS_BASE_URL=https://…run.app npx playwright test -c playwright.deployed.config.ts
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /judge-safety\.spec\.ts/,
  outputDir: "./test-results/deployed",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.FS_BASE_URL,
    viewport: { width: 1600, height: 900 },
  },
});
