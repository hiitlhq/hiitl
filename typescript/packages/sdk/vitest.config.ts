import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    // Preserve the prior runner's mock lifecycle; each test's own setup controls its mocks.
    clearMocks: false,
    environment: 'node',
    include: ['tests/**/*.test.ts'],
    // the unit suite runs with the network refused (HTL-22 row 180); the setup guards its own directory
    setupFiles: ['tests/unit/offline.ts'],
    // each test runs in a directory of its own, set in that setup; a worker thread cannot change it, a forked process can
    pool: 'forks',
  },
});
