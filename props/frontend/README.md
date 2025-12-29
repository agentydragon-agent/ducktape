# Props Frontend

SvelteKit-based web interface for viewing Props evaluation results.

## Development

```bash
# Install dependencies
pnpm install

# Start dev server
pnpm dev

# Build for production
pnpm build

# Type check
pnpm check

# Lint & format
pnpm lint
pnpm format
```

## OpenAPI Types

Regenerate TypeScript types from backend API schema:

```bash
pnpm generate  # Requires backend running at http://127.0.0.1:8000
```

## Storybook & Visual Testing

Storybook for component development, Playwright for visual regression testing.

```bash
# Run Storybook (http://localhost:6006)
pnpm storybook

# Visual regression tests
pnpm test:visual         # Compare against baselines
pnpm test:visual:update  # Update baselines after intentional changes
pnpm test:visual:ui      # Interactive UI mode
```

Add stories in `src/**/*.stories.ts` (see existing examples). Baselines are stored in `tests/visual-regression.spec.ts-snapshots/` (committed to git).
