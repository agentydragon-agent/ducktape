// Prettier configuration
// https://prettier.io/docs/en/options.html
//
// Svelte plugin setup:
// - Local dev: plugin found in node_modules via local package.json
// - Pre-commit (CI): plugin excluded (svelte files excluded from types_or)
// - Bazel: handles svelte formatting via rules_lint prettier aspect
//
// See: https://github.com/prettier/prettier/issues/15696

// Try to resolve svelte plugin - may not be available in all environments
let plugins = [];
try {
  plugins = [require.resolve("prettier-plugin-svelte")];
} catch {
  // Plugin not available in this environment (e.g., pre-commit CI)
  // Svelte files will be excluded from formatting in that case
}

module.exports = {
  printWidth: 120,
  tabWidth: 2,
  useTabs: false,
  semi: true,
  singleQuote: false,
  trailingComma: "es5",
  bracketSpacing: true,
  plugins,
  overrides: [
    {
      files: "*.svelte",
      options: {
        parser: "svelte",
      },
    },
  ],
};
