import { main } from '../../../util/testing/frontend_visual/visual-test-lib.mjs';

await main('DetailPage', import.meta.url, {
  baselineName: 'DetailPage_mobile',
  viewport: { width: 375, height: 812 },
});
