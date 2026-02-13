/**
 * Output raw measureText().width values (full float precision) to diagnose
 * why widths differ between gVisor and RBE. Serves font via HTTP like the
 * real visual regression test (data: URLs don't load @font-face).
 */
import puppeteer from "puppeteer";
import { join, resolve } from "path";
import { existsSync, readFileSync } from "fs";
import { createServer } from "http";

const FONT_URL = process.env.FONT_WOFF2_PATH;
const TEST_CHARS = [
  "A", "B", "C", "M", "W",
  "a", "e", "g", "o", "s",
  "0", "1", "3", "8", "9",
  ".", ",", ":", ";",
  "@", "&", "%",
];
const SIZES = [12, 16, 24, 48];

async function main() {
  let execPath = process.env.PUPPETEER_EXECUTABLE_PATH || "";
  const playwrightExec = join(execPath, "chrome-linux", "headless_shell");
  if (existsSync(playwrightExec)) {
    execPath = playwrightExec;
  }

  if (!execPath || !existsSync(execPath)) {
    console.error("Chrome binary not found");
    process.exit(1);
  }

  // Read font file
  const fontPath = FONT_URL ? resolve(FONT_URL) : null;
  const fontData = fontPath && existsSync(fontPath)
    ? readFileSync(fontPath)
    : null;

  // Start HTTP server to serve the font (data: URLs don't load @font-face)
  const server = createServer((req, res) => {
    if (req.url === "/Inter.woff2" && fontData) {
      res.writeHead(200, { "Content-Type": "font/woff2" });
      res.end(fontData);
    } else if (req.url === "/") {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(buildHTML());
      return;
    } else {
      res.writeHead(404);
      res.end("Not found");
    }
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  console.log(`Font server on http://127.0.0.1:${port}`);

  function buildHTML() {
    return `<!DOCTYPE html>
<html>
<head>
<style>
@font-face {
  font-family: "Inter";
  src: url("http://127.0.0.1:${port}/Inter.woff2") format("woff2");
  font-weight: 100 900;
  font-display: block;
}
* { margin: 0; padding: 0; }
</style>
</head>
<body>
<canvas id="c" width="800" height="600"></canvas>
<script>
async function measure() {
  await document.fonts.ready;

  const fontCheck = {};
  for (const size of ${JSON.stringify(SIZES)}) {
    fontCheck[size + 'px'] = document.fonts.check(size + 'px Inter');
  }

  const canvas = document.getElementById('c');
  const ctx = canvas.getContext('2d');

  const results = [];
  const chars = ${JSON.stringify(TEST_CHARS)};
  const sizes = ${JSON.stringify(SIZES)};

  for (const size of sizes) {
    ctx.font = size + 'px Inter, sans-serif';
    ctx.textBaseline = 'top';

    for (const ch of chars) {
      const m = ctx.measureText(ch);
      results.push({
        ch,
        size,
        width: m.width,
        actualBoundingBoxLeft: m.actualBoundingBoxLeft,
        actualBoundingBoxRight: m.actualBoundingBoxRight,
        fontBoundingBoxAscent: m.fontBoundingBoxAscent,
        fontBoundingBoxDescent: m.fontBoundingBoxDescent,
      });
    }
  }

  return { fontCheck, results };
}

window.__measureResults = measure();
</script>
</body>
</html>`;
  }

  const userDataDir = join(
    process.env.TEST_TMPDIR || "/tmp",
    "chrome-width-test"
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
    await new Promise((r) => setTimeout(r, 1000));

    const data = await page.evaluate(async () => await window.__measureResults);

    console.log("========== FONT CHECK ==========");
    for (const [size, loaded] of Object.entries(data.fontCheck)) {
      console.log(`  Inter ${size}: ${loaded ? "LOADED" : "NOT LOADED"}`);
    }

    console.log("");
    console.log("========== RAW measureText().width ==========");
    console.log("CHAR  SIZE   WIDTH (full precision)       ABBL       ABBR     FB_ASC  FB_DESC");
    for (const r of data.results) {
      const ch = r.ch.padEnd(4);
      const sz = String(r.size).padStart(4);
      console.log(
        `${ch} ${sz}px  ${r.width.toFixed(20).padStart(28)}  ${r.actualBoundingBoxLeft.toFixed(10).padStart(14)}  ${r.actualBoundingBoxRight.toFixed(10).padStart(14)}  ${r.fontBoundingBoxAscent}  ${r.fontBoundingBoxDescent}`
      );
    }

    console.log("");
    console.log("========== DONE ==========");
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
