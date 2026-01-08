// Prettier configuration
// https://prettier.io/docs/en/options.html
//
// Svelte plugin disabled due to Prettier 3.x limitations.
// See: docs/ci/prettier-limitations.md

module.exports = {
  printWidth: 120,
  tabWidth: 2,
  useTabs: false,
  semi: true,
  singleQuote: false,
  trailingComma: "es5",
  bracketSpacing: true,
};
