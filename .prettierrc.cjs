// Prettier configuration
// https://prettier.io/docs/en/options.html
//
// TODO: Re-enable prettier-plugin-svelte once Prettier 3.x plugin resolution is fixed.
// Currently disabled because Prettier 3.x resolves plugins relative to the config file,
// not from where prettier is installed. This breaks both pre-commit CI and Bazel.
// See: https://github.com/prettier/prettier/issues/15696
//
// Svelte files are excluded from prettier formatting. For svelte formatting options:
// - Use your IDE's svelte extension (e.g., Svelte for VS Code)
// - Run: pnpm exec prettier --plugin prettier-plugin-svelte --write "**/*.svelte"

module.exports = {
  printWidth: 120,
  tabWidth: 2,
  useTabs: false,
  semi: true,
  singleQuote: false,
  trailingComma: "es5",
  bracketSpacing: true,
};
