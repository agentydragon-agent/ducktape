/**
 * Render individual glyphs to Canvas, extract raw pixel data as hex.
 * Run on both gVisor and RBE to get per-glyph, per-pixel diffs.
 *
 * Usage: node render_glyphs.mjs
 * Requires: PUPPETEER_EXECUTABLE_PATH, FONTCONFIG_FILE, FREETYPE_PROPERTIES env vars
 */
import puppeteer from "puppeteer";
import { createHash } from "crypto";
import { join, dirname, resolve } from "path";
import { existsSync, readFileSync } from "fs";

const FONT_URL = process.env.FONT_WOFF2_PATH;

// Characters to test — mix of simple, complex, and edge-case glyphs
const TEST_CHARS = [
  "A", "B", "C", "M", "W", // wide capitals
  "a", "e", "g", "o", "s", // common lowercase
  "0", "1", "3", "8", "9", // digits
  ".", ",", ":", ";",       // punctuation
  "@", "&", "%",            // complex glyphs
];

const SIZES = [12, 16, 24, 48]; // test multiple sizes

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

  const userDataDir = join(
    process.env.TEST_TMPDIR || "/tmp",
    "chrome-glyph-test"
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
      "--disable-features=CalculateNativeWinOcclusion,VizDisplayCompositor",
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({
      width: 800,
      height: 600,
      deviceScaleFactor: 1,
    });

    // Build a data URL with the Inter font embedded as base64
    let fontFaceCSS = "";
    if (FONT_URL) {
      const fontPath = resolve(FONT_URL);
      if (existsSync(fontPath)) {
        const fontData = readFileSync(fontPath);
        const fontB64 = fontData.toString("base64");
        fontFaceCSS = `
          @font-face {
            font-family: 'Inter';
            src: url(data:font/woff2;base64,${fontB64}) format('woff2');
            font-weight: 100 900;
            font-display: block;
          }
        `;
      }
    }

    const html = `<!DOCTYPE html>
<html>
<head>
<style>
${fontFaceCSS}
* { margin: 0; padding: 0; }
canvas { display: block; }
</style>
</head>
<body>
<canvas id="c" width="800" height="600"></canvas>
<script>
async function renderGlyphs() {
  // Wait for Inter font to load
  await document.fonts.ready;

  const canvas = document.getElementById('c');
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const results = {};

  const chars = ${JSON.stringify(TEST_CHARS)};
  const sizes = ${JSON.stringify(SIZES)};

  for (const size of sizes) {
    for (const ch of chars) {
      // Clear canvas
      ctx.clearRect(0, 0, 800, 600);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, 800, 600);

      // Render character
      ctx.fillStyle = '#000000';
      ctx.font = size + 'px Inter, sans-serif';
      ctx.textBaseline = 'top';
      ctx.fillText(ch, 10, 10);

      // Measure the glyph bounding box
      const metrics = ctx.measureText(ch);
      const w = Math.ceil(metrics.width) + 20;
      const h = size + 20;

      // Extract pixel data for the glyph region
      const imageData = ctx.getImageData(0, 0, Math.min(w, 100), Math.min(h, 100));
      const data = imageData.data;

      // Hash the pixel data (faster than dumping all bytes)
      let hash = 0;
      let nonWhitePixels = 0;
      // Also collect the actual alpha channel values for the glyph area
      const alphas = [];
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i], g = data[i+1], b = data[i+2], a = data[i+3];
        // Simple hash
        hash = ((hash << 5) - hash + r + g + b + a) | 0;
        if (r < 255 || g < 255 || b < 255) {
          nonWhitePixels++;
        }
        // Collect alpha values of non-white pixels for detailed comparison
        if (r < 250) {
          alphas.push(r); // grayscale, so r=g=b
        }
      }

      const key = ch + '@' + size + 'px';
      results[key] = {
        hash: (hash >>> 0).toString(16).padStart(8, '0'),
        nonWhitePixels: nonWhitePixels,
        width: imageData.width,
        height: imageData.height,
        // First 50 non-white pixel values for detailed comparison
        sampleAlphas: alphas.slice(0, 50),
      };
    }
  }
  return results;
}

window.__glyphResults = renderGlyphs();
</script>
</body>
</html>`;

    const dataUrl =
      "data:text/html;base64," + Buffer.from(html).toString("base64");
    await page.goto(dataUrl, { waitUntil: "networkidle0" });

    // Wait a bit for font loading and rendering
    await new Promise((r) => setTimeout(r, 1000));

    const results = await page.evaluate(async () => {
      return await window.__glyphResults;
    });

    // Print results in a diffable format
    console.log("========== GLYPH PIXEL DATA ==========");
    console.log(`HOSTNAME=${process.env.HOSTNAME || "unknown"}`);
    console.log(`KERNEL=${process.env.KERNEL || "unknown"}`);
    console.log("");

    const keys = Object.keys(results).sort();
    for (const key of keys) {
      const r = results[key];
      const alphaStr = r.sampleAlphas.join(",");
      console.log(
        `${key.padEnd(12)} hash=${r.hash} pixels=${String(r.nonWhitePixels).padStart(5)} dim=${r.width}x${r.height} alphas=[${alphaStr}]`
      );
    }

    console.log("");
    console.log("========== SUMMARY ==========");

    // Also compute an overall hash of all glyph data
    const allHashes = keys.map((k) => results[k].hash).join("");
    const overallHash = createHash("md5").update(allHashes).digest("hex");
    console.log(`OVERALL_HASH=${overallHash}`);
    console.log(`TOTAL_GLYPHS=${keys.length}`);
    console.log("========== DONE ==========");
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
