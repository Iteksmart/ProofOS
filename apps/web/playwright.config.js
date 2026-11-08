import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
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
      // Reset the SQLite DB *before* the server opens it. Doing this in a
      // globalSetup hook is too late: Playwright starts webServers first, so
      // deleting the file afterwards leaves the server writing to a dead handle.
      command: "rm -f e2e.db && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000",
      cwd: "../../services/api",
      url: "http://localhost:8000/health",
      env: {
        ...process.env,
        DATABASE_URL: "sqlite:///./e2e.db",
        JWT_SECRET: "e2e-secret-min-32-chars-long",
        PROOF_SIGNING_SEED_HEX: "00".repeat(32),
        ENV: "development",
      },
      reuseExistingServer: false,
      timeout: 90000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: false,
      timeout: 90000,
    },
  ],
});
