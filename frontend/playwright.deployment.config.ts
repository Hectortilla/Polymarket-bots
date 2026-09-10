import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e-deployment",
  workers: 1,
  timeout: 90_000,
  use: {
    baseURL: "https://localhost:8443",
    // The disposable Compose harness generates its own local certificate.
    ignoreHTTPSErrors: true,
    trace: "off",
  },
});
