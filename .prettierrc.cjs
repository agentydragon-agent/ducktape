// Prettier configuration
// https://prettier.io/docs/en/options.html
//
// Svelte plugin is NOT configured here - svelte formatting is handled only by Bazel.
//
// Why: Prettier 3.x resolves plugins relative to the config file, not from where
// prettier is installed. This breaks pre-commit's isolated node environment.
// Even try/catch with require.resolve() doesn't work because require.resolve()
// succeeds (finding the package) but prettier then fails to load it.
//
// Approaches tried that all fail:
// - mirrors-prettier with additional_dependencies: [prettier-plugin-svelte]
// - jvllmr/pre-commit-prettier fork (designed for plugin support)
// - .cjs file with require.resolve() in try/catch
// - npx --package=prettier-plugin-svelte
//
// All produce: "Cannot find package 'prettier-plugin-svelte' imported from .../noop.js"
//
// Root cause: https://github.com/prettier/prettier/issues/15696
//
// For svelte formatting, use: bazel build --config=lint //...

module.exports = {
  printWidth: 120,
  tabWidth: 2,
  useTabs: false,
  semi: true,
  singleQuote: false,
  trailingComma: "es5",
  bracketSpacing: true,
};
