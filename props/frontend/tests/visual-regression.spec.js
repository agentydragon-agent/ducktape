import puppeteer from 'puppeteer';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { PNG } from 'pngjs';
import pixelmatch from 'pixelmatch';
import { fileURLToPath } from 'url';
import { dirname, join, extname } from 'path';
import { createServer } from 'http';
import { readFile } from 'fs/promises';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Update mode: set UPDATE_BASELINES=1 to overwrite existing baselines
const UPDATE_BASELINES = process.env.UPDATE_BASELINES === '1';

// Component scenarios to test (mirrors harness.ts)
const scenarios = [
  { component: 'BackButton', scenario: 'Default' },
  { component: 'BackButton', scenario: 'CustomLabel' },
  { component: 'BackButton', scenario: 'CustomHref' },
  { component: 'BackButton', scenario: 'CustomClass' },
  { component: 'Breadcrumb', scenario: 'SingleItem' },
  { component: 'Breadcrumb', scenario: 'WithPath' },
  { component: 'Breadcrumb', scenario: 'DeepPath' },
  { component: 'Breadcrumb', scenario: 'AllLinked' },
  { component: 'CopyButton', scenario: 'Default' },
  { component: 'CopyButton', scenario: 'CustomLabel' },
  { component: 'CopyButton', scenario: 'CustomSuccessMessage' },
  { component: 'CopyButton', scenario: 'LongText' },
];

const CONTENT_TYPES = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

async function startServer(harnessDir) {
  const server = createServer(async (req, res) => {
    let urlPath = req.url.split('?')[0];
    if (urlPath === '/') urlPath = '/index.html';

    const filePath = join(harnessDir, urlPath);

    try {
      const content = await readFile(filePath);
      const ext = extname(filePath);
      res.setHeader('Content-Type', CONTENT_TYPES[ext] || 'application/octet-stream');
      res.writeHead(200);
      res.end(content);
    } catch (err) {
      if (err.code === 'ENOENT') {
        res.writeHead(404);
        res.end('Not found: ' + urlPath);
      } else {
        res.writeHead(500);
        res.end('Server error: ' + err.message);
      }
    }
  });

  return new Promise((resolve) => {
    server.listen(0, () => {
      const port = server.address().port;
      resolve({ server, port });
    });
  });
}

function compareBaseline(name, screenshot) {
  // Use same naming convention as Playwright for compatibility with existing baselines
  const baselineDir = join(__dirname, 'visual-regression.spec.ts-snapshots');
  const baselinePath = join(baselineDir, `${name}-chromium-linux.png`);
  const diffDir = join(__dirname, 'diffs');

  if (!existsSync(diffDir)) {
    mkdirSync(diffDir, { recursive: true });
  }

  // Update mode: always overwrite baselines
  if (UPDATE_BASELINES) {
    console.log(`  Updating baseline: ${name}`);
    if (!existsSync(baselineDir)) {
      mkdirSync(baselineDir, { recursive: true });
    }
    writeFileSync(baselinePath, screenshot);
    return { passed: true, updated: true };
  }

  if (!existsSync(baselinePath)) {
    console.log(`  Creating baseline: ${name}`);
    if (!existsSync(baselineDir)) {
      mkdirSync(baselineDir, { recursive: true });
    }
    writeFileSync(baselinePath, screenshot);
    return { passed: true, created: true };
  }

  const baseline = PNG.sync.read(readFileSync(baselinePath));
  const actual = PNG.sync.read(screenshot);

  if (actual.width !== baseline.width || actual.height !== baseline.height) {
    console.error(
      `  ✗ Dimensions differ: baseline=${baseline.width}x${baseline.height}, actual=${actual.width}x${actual.height}`
    );
    writeFileSync(join(diffDir, `${name}-actual.png`), screenshot);
    return { passed: false, reason: 'dimensions' };
  }

  const diff = new PNG({ width: baseline.width, height: baseline.height });
  const numDiffPixels = pixelmatch(baseline.data, actual.data, diff.data, baseline.width, baseline.height, {
    threshold: 0.1,
  });

  if (numDiffPixels > 0) {
    writeFileSync(join(diffDir, `${name}-actual.png`), screenshot);
    writeFileSync(join(diffDir, `${name}-diff.png`), PNG.sync.write(diff));
    console.error(`  ✗ ${numDiffPixels} pixels differ`);
    return { passed: false, reason: 'pixels', diffCount: numDiffPixels };
  }

  return { passed: true };
}

async function runVisualTests() {
  // Get harness path from environment (set by Bazel) or use default
  const harnessPath = process.env.HARNESS_PATH || join(__dirname, 'harness/dist/harness.js');
  // harnessDir is the parent of dist, containing both index.html and dist/
  const distDir = dirname(harnessPath);
  const harnessDir = distDir.endsWith('/dist') || distDir.endsWith('\\dist') ? dirname(distDir) : distDir;

  console.log(`Harness directory: ${harnessDir}`);

  if (!existsSync(join(harnessDir, 'index.html'))) {
    console.error(`Harness index.html not found in: ${harnessDir}`);
    process.exit(1);
  }

  const { server, port } = await startServer(harnessDir);
  console.log(`Server started on port ${port}`);

  // Use PUPPETEER_EXECUTABLE_PATH if set (for Bazel-managed or system Chrome)
  // Playwright browser directories have structure: dir/chrome-linux/headless_shell
  const launchOptions = {
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  };
  if (process.env.PUPPETEER_EXECUTABLE_PATH) {
    let execPath = process.env.PUPPETEER_EXECUTABLE_PATH;
    // rules_playwright provides a directory - construct path to actual executable
    const playwrightExec = join(execPath, 'chrome-linux', 'headless_shell');
    if (existsSync(playwrightExec)) {
      execPath = playwrightExec;
    }
    console.log(`Using browser at: ${execPath}`);
    launchOptions.executablePath = execPath;
  }
  const browser = await puppeteer.launch(launchOptions);

  let passed = 0;
  let failed = 0;
  let created = 0;
  let updated = 0;

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 800, height: 600 });

    for (const { component, scenario } of scenarios) {
      const name = `${component}-${scenario}`;
      console.log(`Testing: ${name}`);

      const url = `http://localhost:${port}/?component=${component}&scenario=${scenario}`;
      await page.goto(url, { waitUntil: 'networkidle0' });

      // Wait for component to render
      await page.waitForSelector('#app > *', { timeout: 5000 });

      // Give animations time to complete
      await new Promise((r) => setTimeout(r, 200));

      // Take screenshot of the app container
      const element = await page.$('#app');
      const screenshotData = await element.screenshot();
      // Ensure we have a Buffer (Puppeteer might return Uint8Array)
      const screenshot = Buffer.isBuffer(screenshotData) ? screenshotData : Buffer.from(screenshotData);

      const result = compareBaseline(name, screenshot);

      if (result.updated) {
        updated++;
        console.log(`  ✓ Baseline updated`);
      } else if (result.created) {
        created++;
        console.log(`  ✓ Baseline created`);
      } else if (result.passed) {
        passed++;
        console.log(`  ✓ Passed`);
      } else {
        failed++;
      }
    }
  } finally {
    await browser.close();
    server.close();
  }

  console.log('');
  console.log('='.repeat(50));
  if (UPDATE_BASELINES) {
    console.log(`Results: ${updated} baselines updated`);
  } else {
    console.log(`Results: ${passed} passed, ${failed} failed, ${created} baselines created`);
  }
  console.log('='.repeat(50));

  process.exit(failed > 0 ? 1 : 0);
}

runVisualTests().catch((err) => {
  console.error('Test failed with error:', err);
  process.exit(1);
});
