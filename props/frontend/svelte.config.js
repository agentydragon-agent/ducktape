import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// Use different output dir for Storybook to avoid Bazel action conflict with svelte_kit_sync
// Detect Storybook by checking process.argv (more reliable than env var in Bazel sandbox)
const isStorybook =
  process.env.STORYBOOK === '1' ||
  process.env.STORYBOOK === 'true' ||
  process.argv.some((arg) => arg.includes('storybook'));
const outDir = isStorybook ? '.svelte-kit-storybook' : '.svelte-kit';

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
