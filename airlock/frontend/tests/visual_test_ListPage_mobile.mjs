import { main } from '../../../util/testing/frontend_visual/visual-test-lib.mjs';

await main('ListPage', import.meta.url, {
  baselineName: 'ListPage_mobile',
  viewport: { width: 375, height: 812 },
});
