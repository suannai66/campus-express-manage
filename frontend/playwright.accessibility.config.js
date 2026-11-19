import { defineConfig } from "@playwright/test";
import verification from "./playwright.verification.config.js";

// Use an independent SQLite database and ports for browser accessibility tests.
export default defineConfig({
  ...verification,
  testMatch: "*-a11y.spec.js",
  use: { ...verification.use, baseURL: "http://127.0.0.1:18182" },
  webServer: [
    {
      ...verification.webServer[0],
      command: verification.webServer[0].command.replace("18151", "18181"),
      url: "http://127.0.0.1:18181/api/health",
    },
    {
      ...verification.webServer[1],
      command: verification.webServer[1].command.replace("18152", "18182"),
      url: "http://127.0.0.1:18182",
      env: { CAMPUS_API_TARGET: "http://127.0.0.1:18181" },
    },
  ],
});
