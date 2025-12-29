# Visual Regression Testing

This project uses Storybook + Playwright for visual regression testing of UI components.

## Overview

- **Storybook**: Develop and showcase components in isolation
- **Playwright**: Capture screenshots and compare against baselines
- **Git**: Store baseline screenshots for tracking visual changes

## Quick Start

### 1. Run Storybook (Development)

```bash
pnpm storybook
```

Visit http://localhost:6006 to view and interact with component stories.

### 2. Run Visual Tests

```bash
# Run tests (compare against baselines)
pnpm test:visual

# Update baselines (after intentional visual changes)
pnpm test:visual:update

# Interactive UI mode
pnpm test:visual:ui
```

## Workflow

### Adding New Stories

1. Create a `.stories.svelte` file next to your component:

```svelte
<!-- src/components/MyComponent.stories.svelte -->
<script context="module">
  import MyComponent from './MyComponent.svelte';

  export const meta = {
    title: 'Components/MyComponent',
    component: MyComponent,
    tags: ['autodocs'],
  };
</script>

<script>
  import { Story } from '@storybook/addon-svelte-csf';
</script>

<Story name="Default">
  <MyComponent />
</Story>

<Story name="WithProp">
  <MyComponent prop="value" />
</Story>
```

2. Add the story to `tests/visual-regression.spec.ts`:

```typescript
const stories = [
  // ... existing stories
  { path: '/?path=/story/components-mycomponent--default', name: 'MyComponent-Default' },
  { path: '/?path=/story/components-mycomponent--with-prop', name: 'MyComponent-WithProp' },
];
```

3. Generate baseline screenshots:

```bash
pnpm test:visual:update
```

4. Commit the baseline screenshots in `tests/visual-regression.spec.ts-snapshots/`

### Reviewing Visual Changes

When tests fail due to visual differences:

1. Check the diff in `playwright-report/`:

   ```bash
   npx playwright show-report
   ```

2. Review the changes:
   - **Expected**: What it looked like before
   - **Actual**: What it looks like now
   - **Diff**: Highlighted differences

3. If changes are intentional:

   ```bash
   pnpm test:visual:update
   git add tests/visual-regression.spec.ts-snapshots/
   git commit -m "Update visual baselines after XYZ changes"
   ```

4. If changes are unintentional, fix the code and re-run tests

## CI/CD Integration

The GitHub Action workflow (`.github/workflows/visual-tests.yml`) runs on every PR:

1. Builds Storybook
2. Runs Playwright visual tests
3. Uploads diff reports as artifacts if tests fail
4. Comments on PR with test results

## Files and Directories

```
props/frontend/
├── .storybook/              # Storybook configuration
│   ├── main.ts
│   └── preview.ts
├── src/
│   └── components/
│       └── *.stories.svelte # Component stories
├── tests/
│   ├── visual-regression.spec.ts                    # Test definitions
│   └── visual-regression.spec.ts-snapshots/         # Baseline screenshots (committed to git)
│       └── *.png
├── playwright.config.ts     # Playwright configuration
├── playwright-report/       # Test results (not committed)
└── test-results/           # Test artifacts (not committed)
```

## Tips

- Baseline screenshots are **committed to git** - they're your source of truth
- Use descriptive story names for clear test failure messages
- Disable animations in stories for consistent screenshots
- Test multiple states: default, loading, error, edge cases
- Keep stories focused - one story per component state
