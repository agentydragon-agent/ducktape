import { test, expect } from '@playwright/test';

// Stories to test for visual regression
const stories = [
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
