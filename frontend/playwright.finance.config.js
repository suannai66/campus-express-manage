import { defineConfig } from "@playwright/test";
import fulfillment from "./playwright.fulfillment.config.js";
export default defineConfig({
  ...fulfillment,
  testMatch: "finance.spec.js",
  timeout: 60000,
  use: {
    ...fulfillment.use,
    baseURL: "http://127.0.0.1:18172",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      ...fulfillment.webServer[0],
      command: fulfillment.webServer[0].command.replace("18161", "18171"),
      url: "http://127.0.0.1:18171/api/health",
    },
    {
      ...fulfillment.webServer[1],
      command: "npm run dev -- --port 18172 --strictPort",
      url: "http://127.0.0.1:18172",
      env: { CAMPUS_API_TARGET: "http://127.0.0.1:18171" },
    },
  ],
});
