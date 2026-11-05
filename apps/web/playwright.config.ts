import { defineConfig } from '@playwright/test';

const port = Number(process.env.E2E_PORT ?? 18765);

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    // Falls back to an installed Chrome, so local runs need no browser download.
    channel: process.env.CI ? undefined : 'chrome',
  },
  webServer: {
    // Serves the built app. A fresh database per run keeps the tests independent.
    command: `rm -f .e2e.db .e2e.db-shm .e2e.db-wal && MOCKFORGE_DATABASE_URL=sqlite:///./.e2e.db ../../.venv/bin/uvicorn mockforge_api.asgi:app --port ${port} --log-level warning`,
    url: `http://127.0.0.1:${port}/api/workspaces`,
    reuseExistingServer: false,
  },
});
