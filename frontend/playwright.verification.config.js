import { defineConfig } from "@playwright/test";
import identity from "./playwright.identity.config.js";
// 复用隔离数据库和演示验证码；只替换测试专用启动入口与端口。
export default defineConfig({
  ...identity,
  testMatch: "verification.spec.js",
  use: { ...identity.use, baseURL: "http://127.0.0.1:18152" },
  webServer: [
    {
      ...identity.webServer[0],
      command: identity.webServer[0].command
        .replace("app.main:app", "tests.verification_browser_app:app")
        .replace("18141", "18151"),
      url: "http://127.0.0.1:18151/api/health",
    },
    {
      ...identity.webServer[1],
      command: "npm run dev -- --port 18152 --strictPort",
      url: "http://127.0.0.1:18152",
      env: { CAMPUS_API_TARGET: "http://127.0.0.1:18151" },
    },
  ],
});
