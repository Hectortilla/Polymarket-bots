import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../backend/contracts/openapi/control-plane.json",
  output: "src/lib/api/generated",
  plugins: ["@hey-api/client-fetch"],
});
