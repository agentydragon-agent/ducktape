import { defineConfig } from 'vitest/config'
import { svelte, vitePreprocess } from '@sveltejs/vite-plugin-svelte'
import { fileURLToPath } from 'node:url'
import type { Plugin } from 'vite'

// Workaround plugin to fix Svelte HMR plugin crash in vitest
// The hot-update plugin tries to access server.environments which doesn't exist in vitest
const fixSvelteHmr = (): Plugin => ({
  name: 'fix-svelte-hmr',
  enforce: 'pre',
  configureServer(server: any) {
    // Provide a minimal environments object to prevent crash
    if (!server.environments) {
      server.environments = {}
    }
  },
})

export default defineConfig({
  plugins: [
    fixSvelteHmr(),
    svelte({
      compilerOptions: {
        // Enable Svelte 5 runes mode
        runes: true,
      },
      // Disable HMR for testing
      hot: false,
      // Use vite preprocessing
      preprocess: vitePreprocess(),
    }),
  ],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    root: fileURLToPath(new URL('./', import.meta.url)),
    globals: true,
    setupFiles: [],
  },
  resolve: {
    conditions: ['browser'],
  },
})
