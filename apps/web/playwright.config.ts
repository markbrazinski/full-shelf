import { defineConfig } from "@playwright/test";

const webPort = process.env.FULL_SHELF_WEB_PORT ?? "5173";
const replayUrl = process.env.VITE_ORCHESTRATOR_URL ?? "http://127.0.0.1:8787";

// Verification runs against the REAL localhost replay server and a real
// Vite dev server in deterministic mode — never a mock.
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    viewport: { width: 1600, height: 900 },
    // Acceptance frames must stop at the exact replay boundary so repeated
    // captures are byte-stable rather than sampling an in-flight tween.
    reducedMotion: "reduce",
    screenshot: "off",
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
    url: `http://127.0.0.1:${webPort}`,
    reuseExistingServer: true,
    timeout: 60_000,
    env: {
      VITE_DATA_SOURCE: "deterministic_replay",
      VITE_ORCHESTRATOR_URL: replayUrl,
    },
  },
});
