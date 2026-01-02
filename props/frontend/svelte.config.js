import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// Use different output dir for Storybook to avoid Bazel action conflict with svelte_kit_sync
const outDir = process.env.STORYBOOK ? '.svelte-kit-storybook' : '.svelte-kit';

/** @type {import('@sveltejs/kit').Config} */
export default {
  preprocess: vitePreprocess(),
  kit: {
    outDir,
    adapter: adapter({
      pages: 'dist',
      assets: 'dist',
      fallback: 'index.html', // SPA mode - all routes go to index.html
    }),
    alias: {
      $components: 'src/components',
    },
  },
};
