import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const api = process.env.MOCKLOOM_API ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    fs: { allow: ['../..'] }, // The example spec lives in the repo's examples/ folder.
    proxy: {
      '/api': { target: api, ws: true },
      '/mock': { target: api },
    },
  },
  build: { chunkSizeWarningLimit: 4000 },
  test: { include: ['src/**/*.test.ts'] },
});
