import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: false, // if 5173 is busy, Vite will bump to 5174+, proxy still applies
    proxy: {
      '/ws': {
        target: 'http://127.0.0.1:8765',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "../static/web", emptyOutDir: true },
})
