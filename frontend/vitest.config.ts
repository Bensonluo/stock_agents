import { defineConfig } from 'vitest/config'
import path from 'path'
import react from '@vitejs/plugin-react'

// Round 1 of the frontend regression net was pure-TS logic tests in the node
// environment; round 4 adds component tests. plugin-react compiles JSX for
// test files even though Next pins tsconfig `jsx: preserve` (the Babel
// automatic runtime ignores that setting). Component tests opt into jsdom
// per file via a `// @vitest-environment jsdom` first-line docblock —
// environmentMatchGlobs was removed in vitest 4, and the per-file comment
// is its lightest official replacement. The `@` alias mirrors tsconfig
// paths so tests import modules exactly like application code.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test/setup.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
})
