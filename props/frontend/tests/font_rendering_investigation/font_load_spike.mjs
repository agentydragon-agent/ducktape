/**
 * Spike test: verify Inter font loads correctly on both gVisor and RBE.
 * Serves font via HTTP (data: URLs don't work for @font-face).
 * Takes a screenshot so we can visually confirm it's Inter, not a fallback.
 *
 * Inter has distinctive features:
 * - Single-story 'a' (no hood), double-story 'g'
 * - Tabular figures by default
 * - Thin strokes on '$' and '%'
 */
import puppeteer from "puppeteer";
import { join, resolve } from "path";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "fs";
import { createServer } from "http";

const FONT_URL = process.env.FONT_WOFF2_PATH;

async function main() {
  let execPath = process.env.PUPPETEER_EXECUTABLE_PATH || "";
  const playwrightExec = join(execPath, "chrome-linux", "headless_shell");
  if (existsSync(playwrightExec)) execPath = playwrightExec;

  if (!execPath || !existsSync(execPath)) {
    console.error("Chrome binary not found");
    process.exit(1);
  }

  const fontPath = FONT_URL ? resolve(FONT_URL) : null;
  const fontData =
    fontPath && existsSync(fontPath) ? readFileSync(fontPath) : null;

  if (!fontData) {
    console.error("Font file not found");
    process.exit(1);
  }

  console.log(`Font file: ${fontPath} (${fontData.length} bytes)`);

  // HTTP server for font
  const server = createServer((req, res) => {
    if (req.url === "/Inter.woff2") {
      res.writeHead(200, {
        "Content-Type": "font/woff2",
        "Access-Control-Allow-Origin": "*",
      });
      res.end(fontData);
    } else if (req.url === "/") {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(buildHTML());
    } else {
      res.writeHead(404);
      res.end("Not found");
    }
  });

  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;
  console.log(`Server: http://127.0.0.1:${port}`);

  function buildHTML() {
    return `<!DOCTYPE html>
<html>
<head>
<style>
@font-face {
  font-family: "Inter";
  src: url("/Inter.woff2") format("woff2");
  font-weight: 100 900;
  font-display: block;
}
body {
  margin: 20px;
  background: white;
  font-family: "Inter", sans-serif;
}
.label {
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}
.sample {
  font-size: 32px;
  margin-bottom: 16px;
  color: black;
  line-height: 1.4;
}
.small { font-size: 16px; }
.large { font-size: 48px; }
.mono-compare {
  font-family: monospace;
  font-size: 32px;
  color: #888;
  margin-bottom: 16px;
}
</style>
</head>
<body>
<div class="label">Inter (should have single-story 'a', distinctive 'g'):</div>
<div class="sample">abcdefghijklm ABCDEFGHIJKLM</div>
<div class="sample">nopqrstuvwxyz NOPQRSTUVWXYZ</div>
<div class="sample">0123456789 @#$%&amp;*()!?</div>
<div class="sample small">The quick brown fox jumps over the lazy dog. 0123456789</div>
<div class="sample large">Hag &amp; fig</div>
<div class="label">System monospace (reference - should look different):</div>
<div class="mono-compare">abcdefg 0123456789</div>
<div id="status" style="font-size: 14px; margin-top: 20px; color: blue;"></div>
<script>
document.fonts.ready.then(() => {
  const loaded = document.fonts.check('32px Inter');
  const el = document.getElementById('status');
  el.textContent = 'Inter font loaded: ' + loaded;
  el.style.color = loaded ? 'green' : 'red';

  // Also measure a few key glyphs to output in the page
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  ctx.font = '32px Inter, sans-serif';
  const widths = ['a', 'g', 'W', '@', '0'].map(ch =>
    ch + '=' + ctx.measureText(ch).width.toFixed(6)
  ).join('  ');
  const div = document.createElement('div');
  div.style.cssText = 'font-size: 12px; color: #666; margin-top: 8px;';
  div.textContent = 'measureText @32px: ' + widths;
  document.body.appendChild(div);
});
</script>
</body>
</html>`;
  }

  const userDataDir = join(
    process.env.TEST_TMPDIR || "/tmp",
    "chrome-font-spike"
  );

  const browser = await puppeteer.launch({
    headless: true,
    executablePath: execPath,
    userDataDir,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--single-process",
      "--font-render-hinting=none",
      "--disable-font-subpixel-positioning",
      "--disable-lcd-text",
      "--force-color-profile=srgb",
      "--disable-accelerated-2d-canvas",
      "--disable-gpu-compositing",
      "--disable-software-rasterizer",
      "--disable-skia-runtime-opts",
      "--disable-partial-raster",
      "--use-gl=swiftshader",
      "--force-device-scale-factor=1",
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 800, height: 600, deviceScaleFactor: 1 });

    await page.goto(`http://127.0.0.1:${port}/`, {
      waitUntil: "networkidle0",
    });
    await new Promise((r) => setTimeout(r, 1500));

    // Get font loading status and width data from the page
    const status = await page.evaluate(() => {
      const loaded = document.fonts.check("32px Inter");
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      ctx.font = "32px Inter, sans-serif";
      const widths = {};
      for (const ch of ["a", "g", "W", "@", "0", ".", "H"]) {
        widths[ch] = ctx.measureText(ch).width;
      }
      return { loaded, widths };
    });

    console.log(`\nInter font loaded: ${status.loaded}`);
    console.log("measureText @32px:");
    for (const [ch, w] of Object.entries(status.widths)) {
      console.log(`  '${ch}' = ${w.toFixed(10)}`);
    }

    // Save screenshot as base64 to stdout (sandbox paths don't persist)
    const pngBuf = await page.screenshot({ fullPage: true });
    console.log(`\nScreenshot (${pngBuf.length} bytes):`);
    console.log(`PNG_BASE64_START`);
    console.log(pngBuf.toString("base64"));
    console.log(`PNG_BASE64_END`);

    if (!status.loaded) {
      console.error("\nFAIL: Inter font did not load!");
      process.exit(1);
    }
    console.log("\nPASS: Inter font loaded successfully");
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
