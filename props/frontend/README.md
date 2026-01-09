# Props Frontend

SvelteKit-based web interface for viewing Props evaluation results.

## Development

```bash
# Start all services via devenv (from props/)
cd props && devenv up
```

For standalone commands (rarely needed):

```bash
pnpm install   # Install dependencies
pnpm build     # Build for production
pnpm check     # Type check
pnpm lint      # Lint
pnpm format    # Format
```

## OpenAPI Types

Regenerate TypeScript types from backend API schema:

```bash
pnpm generate  # Requires backend running at http://localhost:8000
```

## Visual Regression Testing

Puppeteer-based visual regression testing via Bazel.

```bash
# Run visual tests (via Bazel)
bazel test //props/frontend:visual_test

# Update baselines after intentional UI changes:
# 1. Build the test harness
cd props/frontend && node tests/harness/esbuild.config.mjs tests/harness/dist

# 2. Run with UPDATE_BASELINES=1 to overwrite baselines
UPDATE_BASELINES=1 HARNESS_PATH=tests/harness/dist/harness.js node tests/visual-regression.spec.js

# 3. Verify the new baselines pass
bazel test //props/frontend:visual_test --nocache_test_results
```

Baselines are stored in `tests/visual-regression.spec.ts-snapshots/` (committed to git). Add test scenarios in `tests/harness/harness.ts`.
