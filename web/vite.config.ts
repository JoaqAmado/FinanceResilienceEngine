import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  build: {
    // one bundle (React + Recharts + engine, about 215 kB gzip) served from localhost for the demo
    chunkSizeWarningLimit: 800,
  },
  test: {
    include: ['test/**/*.test.ts'],
    environment: 'node',
    testTimeout: 300_000,
  },
});
