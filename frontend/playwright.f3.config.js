import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import os from "node:os";

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
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:18132",
    channel: process.env.PW_BROWSER_CHANNEL || undefined,
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18131`,
      cwd: project,
      url: "http://127.0.0.1:18131/api/health",
      env: {
        F3_DEPENDENCY_MODE: "demo",
        CAMPUS_DATABASE_PATH: path.join(
          os.tmpdir(),
          `campus-browser-${process.pid}.db`,
        ),
      },
    },
    {
      command: "npm run dev -- --port 18132 --strictPort",
      url: "http://127.0.0.1:18132",
      env: { CAMPUS_API_TARGET: "http://127.0.0.1:18131" },
    },
  ],
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
