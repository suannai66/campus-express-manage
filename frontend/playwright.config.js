import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  testMatch: "smoke.spec.js",
  use: {
    baseURL: "http://127.0.0.1:5175",
    channel: process.env.PW_BROWSER_CHANNEL || undefined,
  },
  webServer: {
    command: "npm run dev -- --port 5175 --strictPort",
    url: "http://127.0.0.1:5175",
    reuseExistingServer: !process.env.CI,
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
