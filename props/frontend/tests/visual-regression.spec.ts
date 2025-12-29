import { test, expect } from '@playwright/test';

// Stories to test for visual regression
const stories = [
  // Component stories
  { path: '/?path=/story/components-backbutton--default', name: 'BackButton-Default' },
  { path: '/?path=/story/components-backbutton--custom-label', name: 'BackButton-CustomLabel' },
  { path: '/?path=/story/components-backbutton--custom-href', name: 'BackButton-CustomHref' },
  { path: '/?path=/story/components-backbutton--custom-class', name: 'BackButton-CustomClass' },

  { path: '/?path=/story/components-breadcrumb--single-item', name: 'Breadcrumb-SingleItem' },
  { path: '/?path=/story/components-breadcrumb--with-path', name: 'Breadcrumb-WithPath' },
  { path: '/?path=/story/components-breadcrumb--deep-path', name: 'Breadcrumb-DeepPath' },
  { path: '/?path=/story/components-breadcrumb--all-linked', name: 'Breadcrumb-AllLinked' },

  { path: '/?path=/story/components-copybutton--default', name: 'CopyButton-Default' },
  { path: '/?path=/story/components-copybutton--custom-label', name: 'CopyButton-CustomLabel' },
  {
    path: '/?path=/story/components-copybutton--custom-success-message',
    name: 'CopyButton-CustomSuccessMessage',
  },
  { path: '/?path=/story/components-copybutton--long-text', name: 'CopyButton-LongText' },

  // Page stories
  // Note: Some pages require SvelteKit context (getContext, $app/navigation) that Storybook can't provide
  // { path: '/?path=/story/pages-overview--default', name: 'Page-Overview-Default' }, // Requires getContext('runModal')
  { path: '/?path=/story/pages-overview--empty-state', name: 'Page-Overview-EmptyState' },

  { path: '/?path=/story/pages-snapshots-list--default', name: 'Page-SnapshotsList-Default' },
  { path: '/?path=/story/pages-snapshots-list--empty-state', name: 'Page-SnapshotsList-EmptyState' },

  { path: '/?path=/story/pages-snapshot-detail--default', name: 'Page-SnapshotDetail-Default' },

  // { path: '/?path=/story/pages-example-detail--default', name: 'Page-ExampleDetail-Default' }, // Requires component context
  // { path: '/?path=/story/pages-run-detail--default', name: 'Page-RunDetail-Default' }, // Requires component context
  // { path: '/?path=/story/pages-definition-detail--default', name: 'Page-DefinitionDetail-Default' }, // Requires component context
];

for (const story of stories) {
  test(`Visual regression: ${story.name}`, async ({ page }) => {
    await page.goto(story.path);

    // Wait for Storybook iframe to load
    const storyFrame = page.frameLocator('#storybook-preview-iframe');

    // Wait for story to render
    await storyFrame.locator('body').waitFor({ state: 'visible' });

    // Take screenshot and compare
    await expect(storyFrame.locator('body')).toHaveScreenshot(`${story.name}.png`, {
      animations: 'disabled',
    });
  });
}
