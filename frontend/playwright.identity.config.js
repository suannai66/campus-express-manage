import { defineConfig } from "@playwright/test";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const project = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const python = path.join(
  project,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
export default defineConfig({
  testDir: "./tests",
  testMatch: "identity.spec.js",
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:18142",
    channel: process.env.PW_BROWSER_CHANNEL || undefined,
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18141`,
      cwd: project,
      url: "http://127.0.0.1:18141/api/health",
      env: {
        CAMPUS_DATABASE_PATH: path.join(
          os.tmpdir(),
          `campus-identity-${process.pid}-${Date.now()}.db`,
        ),
        CAMPUS_MODE: "demo",
        CAMPUS_DEMO_CODE: "482917",
        CAMPUS_JWT_SECRET:
          "browser-test-only-identity-secret-at-least-32-bytes",
      },
    },
    {
      command: "npm run dev -- --port 18142 --strictPort",
      url: "http://127.0.0.1:18142",
      env: { CAMPUS_API_TARGET: "http://127.0.0.1:18141" },
    },
  ],
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
