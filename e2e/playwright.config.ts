import { defineConfig, devices } from "@playwright/test";

// E-14. Run through `npm run test:e2e` (e2e/run.mjs), which builds the app and sets E2E_PORT to a free port.
const port = Number(process.env.E2E_PORT ?? 3210);

export default defineConfig({
  testDir: ".",
  outputDir: "./test-results",
  fullyParallel: true,
  workers: 4,
  retries: 0,
  forbidOnly: true,
  reporter: [["list"]],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    ...devices["Desktop Chrome"],
    viewport: { width: 1280, height: 800 }, // md: layout, so the side panel is always open
    baseURL: `http://127.0.0.1:${port}`,
    headless: true,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: {
    command: `npx next start -H 127.0.0.1 -p ${port}`,
    cwd: "../web",
    url: `http://127.0.0.1:${port}/data/meta.json`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
