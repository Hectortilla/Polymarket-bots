import { defineConfig } from '@playwright/test';
import { LOGIN_PATH } from './src/lib/auth/navigation';
import contract from './src/lib/runtimeContract.fixture.json' with { type: 'json' };

const HOST = '127.0.0.1';
const BROWSER_PORT = 54173;
const API_PORT = 58015;
const BROWSER_ORIGIN = `http://${HOST}:${BROWSER_PORT}`;
const API_ORIGIN = `http://${HOST}:${API_PORT}`;

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 90_000,
  use: { baseURL: BROWSER_ORIGIN, trace: 'retain-on-failure' },
  webServer: [
    {
      command: `uv run --directory .. python -m control_plane.browser_server --origin ${BROWSER_ORIGIN} --api-host ${HOST} --api-port ${API_PORT}`,
      env: { PYTHONPATH: 'backend/tests' },
      url: API_ORIGIN + contract.apiPaths.health,
      reuseExistingServer: false,
    },
    {
      command: `npm run dev -- --host ${HOST} --port ${BROWSER_PORT} --strictPort`,
      env: { POLYBOT_DEV_API_URL: API_ORIGIN },
      url: BROWSER_ORIGIN + LOGIN_PATH,
      reuseExistingServer: false,
    },
  ],
});
