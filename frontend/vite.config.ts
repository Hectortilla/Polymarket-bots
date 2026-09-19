import { readFileSync } from "node:fs";
import { loadEnv } from "vite";
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => ({
  plugins: [sveltekit()],
  resolve: {
    conditions: ["browser"],
  },
  server: {
    proxy: {
      "^/admin(?:/|$)": {
        target: loadEnv(mode, ".", "POLYBOT_").POLYBOT_DEV_API_URL ?? "http://127.0.0.1:8000",
        changeOrigin: false,
      },
      "/api": loadEnv(mode, ".", "POLYBOT_").POLYBOT_DEV_API_URL ?? "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    provide: {
      liveCapture: (() => {
        const path = loadEnv(mode, ".", "POLYBOT_").POLYBOT_LIVE_CAPTURE;
        return path ? JSON.parse(readFileSync(path, "utf8")) : [];
      })(),
    },
    include: ["src/**/*.test.ts"],
    setupFiles: ["./vitest-setup.ts"],
  },
}));
