import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.js",
  timeout: 60000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000",
      cwd: "../services/api",
      url: "http://localhost:8000/health",
      env: {
        ...process.env,
        DATABASE_URL: "sqlite:///./e2e.db",
        JWT_SECRET: "e2e-secret-min-32-chars-long",
        PROOF_SIGNING_SEED_HEX: "00".repeat(32),
        ENV: "development",
      },
      reuseExistingServer: true,
      timeout: 90000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 90000,
    },
  ],
});
