// Prettier configuration
// https://prettier.io/docs/en/options.html
//
// Svelte plugin: enabled locally, disabled in CI.
//
// In CI (GitHub Actions), Prettier 3.x can't resolve plugins because it looks
// relative to the config file, not from pre-commit's isolated node environment.
// See: https://github.com/prettier/prettier/issues/15696
//
// CI svelte formatting is handled by Bazel: bazel build --config=lint //...

const isCI = process.env.CI || process.env.GITHUB_ACTIONS;

const config = {
  printWidth: 120,
  tabWidth: 2,
  useTabs: false,
  semi: true,
  singleQuote: false,
  trailingComma: "es5",
  bracketSpacing: true,
};

// Only load svelte plugin and overrides when not in CI
if (!isCI) {
  try {
    config.plugins = [require.resolve("prettier-plugin-svelte")];
    config.overrides = [
      {
        files: "*.svelte",
        options: {
          parser: "svelte",
        },
      },
    ];
  } catch {
    // Plugin not installed locally - skip silently
  }
}

module.exports = config;
