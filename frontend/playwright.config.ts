import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

const frontendRoot = process.cwd();
const projectRoot = resolve(frontendRoot, "..");
const testResults = resolve(frontendRoot, "test-results");
const runId = `${process.pid}`;
const backendPort = 8101;
const frontendPort = Number(process.env.VIDEO_EDITOR_E2E_FRONTEND_PORT ?? 3100);
const databasePath = resolve(testResults, `editor-e2e-${runId}.db`);
const storagePath = resolve(testResults, `editor-e2e-storage-${runId}`);
const python = process.env.PYTHON ?? "python";
mkdirSync(testResults, { recursive: true });

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: "list",
  outputDir: resolve(testResults, "playwright"),
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    browserName: "chromium",
    launchOptions: { channel: "chrome" },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${python}" tests/e2e_server.py`,
      cwd: resolve(projectRoot, "backend"),
      url: `http://127.0.0.1:${backendPort}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        DATABASE_URL: `sqlite+aiosqlite:///${databasePath}`,
        PORT: `${backendPort}`,
        STORAGE_PATH: storagePath,
        FRONTEND_TEST_ORIGIN: `http://127.0.0.1:${frontendPort}`,
      },
    },
    {
      command: `npm run dev -- --hostname 127.0.0.1 --port ${frontendPort}`,
      cwd: frontendRoot,
      url: `http://127.0.0.1:${frontendPort}/video-studio`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
