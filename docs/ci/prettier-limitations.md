# Prettier Limitations in CI

## Svelte Plugin Not Working

**Status**: Disabled in all environments (pre-commit, Bazel, CI)

**Root Cause**: Prettier 3.x resolves plugins relative to the config file location, not from where prettier is installed. This fundamentally breaks:

- Pre-commit's isolated node environment
- Bazel's hermetic builds
- Any environment where prettier and plugins are installed separately from the workspace

**Upstream Issue**: https://github.com/prettier/prettier/issues/15696

### Approaches Tried (All Failed)

1. **mirrors-prettier with additional_dependencies**

   ```yaml
   additional_dependencies: [prettier-plugin-svelte]
   ```

   Plugin installs to pre-commit's temp node_modules, but prettier looks in workspace root.

2. **jvllmr/pre-commit-prettier fork**
   Fork designed for plugin support - same resolution issue.

3. **.prettierrc.cjs with require.resolve()**

   ```javascript
   plugins: [require.resolve("prettier-plugin-svelte")];
   ```

   `require.resolve()` succeeds but prettier then fails to load the resolved path.

4. **npx --package=prettier-plugin-svelte**
   Plugin installed but prettier still can't find it.

### Error Message

```
Cannot find package 'prettier-plugin-svelte' imported from /path/to/noop.js
```

### Workarounds for Svelte Formatting

- **IDE**: Use Svelte for VS Code extension (formats on save)
- **Manual**: `pnpm exec prettier --plugin prettier-plugin-svelte --write "**/*.svelte"`

## Markdown Nested List Formatting

**Status**: Accepted limitation

Prettier forcibly inserts blank lines between numbered list items and their nested sub-bullets. This is not configurable.

**Related Issues**:

- https://github.com/prettier/prettier/issues/8004
- https://github.com/prettier/prettier/issues/18005

The formatting is semantically equivalent and doesn't affect rendering.

## Alternatives Considered

| Tool    | Coverage         | Notes                         |
| ------- | ---------------- | ----------------------------- |
| Biome   | JS/TS/JSON/CSS   | Fast, no YAML/Markdown/Svelte |
| dprint  | TS/JSON/Markdown | Plugin-based, no YAML         |
| yamlfmt | YAML only        | Google's tool                 |

Current decision: Keep prettier for JS/TS/CSS/JSON/YAML/HTML/Markdown, accept limitations.
