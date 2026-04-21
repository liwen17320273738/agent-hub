import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// Standalone Vitest config — the main `vite.config.ts` registers a
// dev-time middleware (`wayne-delivery-docs-dev`) that touches the
// filesystem on `configureServer`, which the test runner doesn't need
// (and which can fail in CI). Keep this file focused on test concerns.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/__tests__/**/*.spec.ts'],
    globals: false,
  },
})
