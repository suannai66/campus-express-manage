import { defineConfig } from "@playwright/test";
import verification from "./playwright.verification.config.js";
// 真实 A/B/C/D + 后台事件；仅复用临时库中的虚构审核管理员。
export default defineConfig({
  ...verification,
  testMatch: "fulfillment.spec.js",
  timeout: 60000,
  use: { ...verification.use, baseURL: "http://127.0.0.1:18162" },
  webServer: [
    {
      ...verification.webServer[0],
      command: verification.webServer[0].command.replace("18151", "18161"),
      url: "http://127.0.0.1:18161/api/health",
    },
    {
      ...verification.webServer[1],
      command: "npm run dev -- --port 18162 --strictPort",
      url: "http://127.0.0.1:18162",
      env: { CAMPUS_API_TARGET: "http://127.0.0.1:18161" },
    },
  ],
});
