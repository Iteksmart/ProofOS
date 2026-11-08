import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.js",
  timeout: 60000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 8018",
      cwd: "../services/api",
      url: "http://127.0.0.1:8018/health",
      env: {
        ...process.env,
        DATABASE_URL: "sqlite:///./e2e.db",
        JWT_SECRET: "e2e-secret-min-32-chars-long",
        PROOF_SIGNING_SEED_HEX: "00".repeat(32),
        ENV: "development",
        ALLOW_BOOTSTRAP: "true",
        GOOGLE_CLIENT_ID: "",
        GOOGLE_CLIENT_SECRET: "",
      },
      reuseExistingServer: false,
      timeout: 90000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174",
      url: "http://127.0.0.1:5174",
      env: {
        ...process.env,
        VITE_API_URL: "",
        PROOFOS_API_PROXY_TARGET: "http://127.0.0.1:8018",
      },
      reuseExistingServer: false,
      timeout: 90000,
    },
  ],
});
