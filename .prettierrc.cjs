// Prettier configuration
// https://prettier.io/docs/en/options.html
//
// Svelte plugin setup:
// - Local dev: plugin found in node_modules via local package.json
// - Pre-commit (CI): plugin excluded (svelte files excluded from types_or)
// - Bazel: handles svelte formatting via rules_lint prettier aspect
//
// Why svelte can't work in pre-commit CI:
// Prettier 3.x resolves plugins relative to the config file, not from where
// prettier is installed. Pre-commit installs prettier in an isolated temp
// directory, but looks for plugins in the workspace root where they don't exist.
//
// Approaches tried that all fail:
// - mirrors-prettier with additional_dependencies: [prettier-plugin-svelte]
// - jvllmr/pre-commit-prettier fork (designed for plugin support)
// - This .cjs file with require.resolve() (only works if plugin in local node_modules)
// - npx --package=prettier-plugin-svelte (plugin installed but not found by prettier)
//
// All produce: "Cannot find package 'prettier-plugin-svelte' imported from .../noop.js"
//
// Root cause: https://github.com/prettier/prettier/issues/15696
//
// Try to resolve svelte plugin - only works in local dev with node_modules present
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
