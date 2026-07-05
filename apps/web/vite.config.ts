/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies API calls to the local API service so the UI needs
// no CORS setup; in the Compose deployment the API serves the built assets
// from the same origin.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
});
