import { defineConfig } from 'vitest/config'
import path from 'path'

// Round 1 of the frontend regression net: pure-TS logic tests in the node
// environment (no jsdom / react plugin needed). The `@` alias mirrors
// tsconfig paths so tests import modules exactly like application code.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
})
