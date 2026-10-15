import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API key never reaches the browser: the dev server adds it when proxying /api to FastAPI.
// In production a reverse proxy (behind the company SSO) does the same (docs/HANDOFF.md).
const apiTarget = process.env.AVANT_OFFRE_API_URL ?? "http://127.0.0.1:8000";
const apiKey = process.env.AVANT_OFFRE_API_KEY ?? "";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
        headers: { "X-API-Key": apiKey },
      },
    },
  },
});
