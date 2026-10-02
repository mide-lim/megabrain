import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.VISUAL_PREVIEW_PORT ?? 38000);
export default defineConfig({
  testDir: "./e2e",
  timeout: 60000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: "test-results/visual",
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["json", { outputFile: "test-results/visual-results.json" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:" + port,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    serviceWorkers: "block",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { ...devices["Pixel 7"], defaultBrowserType: "chromium" } },
  ],
  webServer: {
    command: "node ../../tools/visual-preview/serve.mjs",
    url: "http://127.0.0.1:" + port + "/login",
    timeout: 180000,
    reuseExistingServer: false,
  },
});
