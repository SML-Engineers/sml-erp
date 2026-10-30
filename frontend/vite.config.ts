/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the browser talks to Nginx, which sends /api to Django.
// When running `npm run dev` directly, API_PROXY_TARGET points Vite at the backend instead.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";
// Docker on Windows (and macOS) does not pass file-change events into the container, so the
// dev server would keep serving old screens after an update. Checking the files regularly
// instead fixes that; the Docker setup turns it on (deploy/docker-compose.dev.yml).
const polling = process.env.VITE_WATCH_POLLING === "1";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    watch: polling ? { usePolling: true, interval: 1000 } : undefined,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
