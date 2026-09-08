import { loadEnv } from 'vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig(({ mode }) => ({
  plugins: [sveltekit()],
  resolve: {
    conditions: ['browser']
  },
  server: {
    proxy: {
      '/api': loadEnv(mode, '.', 'POLYBOT_').POLYBOT_DEV_API_URL ?? 'http://127.0.0.1:8000'
    }
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    setupFiles: ['./vitest-setup.ts']
  }
}));
