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
