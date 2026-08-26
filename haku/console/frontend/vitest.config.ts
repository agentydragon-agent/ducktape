import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Specs reach vitest already compiled: each is a `ts_library` whose tsc action type-checked
    // it and emitted the `.js` collected here. Nothing in the runfiles needs transforming, which
    // is also why no `esbuild.jsx` setting is needed — the JSX is long since gone.
    include: ["**/*.test.js"],
    environment: "jsdom", // DOMPurify (in markdown.ts) needs a DOM
    // Mantine depends on browser APIs such as matchMedia and ResizeObserver. Run its UI
    // integration spec in an environment that provides those implementations instead of
    // reimplementing them locally in the test.
    environmentMatchGlobs: [["**/route_resource_state.test.js", "happy-dom"]],
  },
  cacheDir: ".vitest-cache",
});
