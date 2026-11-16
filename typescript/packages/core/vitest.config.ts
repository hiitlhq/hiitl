import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    // Preserve the prior runner's mock lifecycle; each test's own setup controls its mocks.
    clearMocks: false,
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
});
