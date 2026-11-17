import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.js",
  timeout: 60000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5184",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    reducedMotion: "reduce",
  },
  webServer: [
    {
      // Reset the database before the server opens it; a later delete fails on Windows while the file is in use.
      command: "python -c \"import os; [os.remove(f) for f in ('e2e.db', 'e2e.db-journal') if os.path.exists(f)]\" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8018",
      cwd: fileURLToPath(new URL("../../services/api", import.meta.url)),
      url: "http://127.0.0.1:8018/health",
      env: {
        ...process.env,
        DATABASE_URL: "sqlite:///./e2e.db",
        JWT_SECRET: "e2e-secret-with-at-least-32-characters",
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
      command: "npm run dev -- --host 127.0.0.1 --port 5184 --strictPort",
      url: "http://127.0.0.1:5184",
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
