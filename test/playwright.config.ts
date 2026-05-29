import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for FinAlly E2E tests.
 *
 * The app under test is served at BASE_URL (default http://localhost:8010,
 * the host port the test compose maps to the container's 8000), a single
 * FastAPI process serving the static Next.js export and the API. Run the app
 * with LLM_MOCK=true so chat responses are deterministic.
 */
const baseURL = process.env.BASE_URL ?? "http://localhost:8010";
const port = new URL(baseURL).port || "8010";

/**
 * Self-contained local server: builds the frontend export, serves it via the
 * backend with the mock LLM + simulator (test/scripts/serve-local.sh). Set
 * EXTERNAL_SERVER=true to skip this and test an already-running instance
 * (e.g. the docker-compose container).
 */
const webServer = process.env.EXTERNAL_SERVER
  ? undefined
  : {
      command: "bash scripts/serve-local.sh",
      url: `${baseURL}/api/health`,
      timeout: 300_000,
      reuseExistingServer: !process.env.CI,
      env: { PORT: port, SKIP_BUILD: process.env.SKIP_BUILD ?? "false" },
    };

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  timeout: 30_000,
  expect: { timeout: 10_000 },
  webServer,
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
