// Prettier configuration
// https://prettier.io/docs/en/options.html
//
// Svelte plugin: Always enabled. Bazel provides the plugin via runfiles (see
// tools/lint/BUILD.bazel prettier_binary data deps). Local dev uses node_modules.

const config = {
  printWidth: 120,
  tabWidth: 2,
  useTabs: false,
  semi: true,
  singleQuote: false,
  trailingComma: "es5",
  bracketSpacing: true,
  plugins: ["prettier-plugin-svelte"],
  overrides: [
    {
      files: "*.svelte",
      options: {
        parser: "svelte",
      },
    },
  ],
};

module.exports = config;
