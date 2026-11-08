import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.PROOFOS_API_PROXY_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: { "/v1": { target: apiTarget, changeOrigin: true, ws: true } },
  },
  resolve: { dedupe: ["react", "react-dom"] },
  optimizeDeps: { exclude: ["@proofos/ui"] },
});
