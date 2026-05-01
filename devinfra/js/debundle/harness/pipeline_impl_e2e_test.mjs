import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

import { launchPuppeteerBrowser } from "../../../../util/testing/frontend_visual/puppeteer-lib.mjs";
import { writeMockSpec } from "./pipeline_impl_golden_lib.mjs";

async function captureState(appRoot) {
  const browser = await launchPuppeteerBrowser({
    args: ["--allow-file-access-from-files", "--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox"],
    headless: true,
  });
  const page = await browser.newPage();
  const consoleMessages = [];
  const pageErrors = [];
  page.on("console", (message) => consoleMessages.push(message.text()));
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  try {
    await page.goto(pathToFileURL(join(appRoot, "index.html")).href, { waitUntil: "networkidle0" });
    await page.waitForFunction(() => globalThis.__mockBundleState?.lazy != null, { timeout: 10_000 });
    const [appText, appBundle, chipText, statusText, state, harnessState] = await Promise.all([
      page.$eval("#app", (node) => node.textContent),
      page.$eval("#app", (node) => node.dataset.bundle),
      page.$eval("#chip", (node) => node.textContent),
      page.$eval("#status", (node) => node.textContent),
      page.evaluate(() => globalThis.__mockBundleState),
      page.evaluate(() => globalThis.__debundleHarness),
    ]);
    assert.equal(
      harnessState.errors.length,
      0,
      `harness errors:\n${JSON.stringify(harnessState.errors, null, 2)}\nconsole:\n${consoleMessages.join("\n")}`
    );
    assert.deepEqual(pageErrors, [], `page errors:\n${pageErrors.join("\n")}\nconsole:\n${consoleMessages.join("\n")}`);
    assert.deepEqual(state, expectedState());
    assert.equal(appBundle, "mock-app");
    assert.equal(appText, JSON.stringify(state.summary));
    assert.equal(chipText, "chip:mock-dashboard@7");
    assert.equal(statusText, "Ada Lovelace:11");
    return state;
  } finally {
    await browser.close();
  }
}

function buildApp(outRoot, impl) {
  const runfiles = process.env.TEST_SRCDIR;
  const workspace = process.env.TEST_WORKSPACE;
  assert.ok(runfiles && workspace, "bazel runfiles env missing");
  const root = join(runfiles, workspace);
  const fixtureRoot = join(root, "devinfra/js/debundle/harness/testdata/mock_browser_bundle/generated");
  const bin = resolveImplementationBin(root, impl);
  const specPath = join(outRoot, "transform-spec.json");
  writeMockSpec(specPath, outRoot, join(fixtureRoot, "snapshot"), join(fixtureRoot, "extracted"));
  const run = spawnSync(bin, ["--spec", specPath], { encoding: "utf8" });
  assert.equal(run.status, 0, `${impl} debundler failed:\nstdout:\n${run.stdout}\nstderr:\n${run.stderr}`);
  return {
    steps: parseStepSummary(run.stdout),
  };
}

function resolveImplementationBin(root, impl) {
  if (impl === "js") {
    return join(root, requiredEnv("JS_DEBUNDLE_BIN"));
  }
  if (impl === "rust") {
    return join(root, requiredEnv("RUST_DEBUNDLE_BIN"));
  }
  throw new Error(`Unknown implementation ${impl}`);
}

function requiredEnv(name) {
  const value = process.env[name];
  assert.ok(value, `${name} missing`);
  return value;
}

function parseStepSummary(stdout) {
  return stdout
    .split("\n")
    .filter((line) => line.startsWith("- "))
    .map((line) => {
      const match = /^- ([^:]+): ([^ ]+) /.exec(line);
      assert.ok(match, `unexpected step summary line: ${line}`);
      return {
        id: match[1],
        operation: match[2],
      };
    });
}

function assertPipelineOutputs(appRoot, steps) {
  assert.deepEqual(
    steps.map((step) => step.operation),
    [
      "load_js_chunks",
      "compute_js_asts",
      "normalize_js_chunks",
      "rewrite_chunk_entry_specifiers",
      "emit_browser_harness",
    ]
  );

  const indexHtml = readFileSync(join(appRoot, "index.html"), "utf8");
  assert.match(indexHtml, /Generated local harness/);
  assert.match(indexHtml, /href="\.\/static\/ActivityPanel-DuckMock\/entry\.js"/);
  assert.match(indexHtml, /href="\.\/static\/SummaryChip-DuckMock\/entry\.js"/);
  assert.match(indexHtml, /href="\.\/static\/chunk-DuckMock\/entry\.js"/);
  assert.ok(readFileSync(join(appRoot, "preload/app.css"), "utf8").includes("font-family"));
}

function expectedState() {
  return {
    chip: {
      text: "chip:mock-dashboard@7",
    },
    lazy: {
      badge: "Ada Lovelace:11",
      stamp: "mock-dashboard@7",
      tags: "analysis,dom",
    },
    model: {
      profileName: "Ada Lovelace",
      tags: ["analysis", "dom"],
      total: 11,
    },
    summary: {
      headline: "Ada Lovelace:11",
      runtime: {
        hasNodeGlobal: false,
        optionalDebugFlag: true,
        rootKind: "globalThis",
      },
      stamp: "mock-dashboard@7",
      tags: "analysis|dom",
      total: 11,
    },
  };
}

const impl = process.env.DEBUNDLE_IMPL;
if (impl === "js" || impl === "rust") {
  const outRoot = mkdtempSync(join(tmpdir(), `debundle-impl-e2e-${impl}-`));
  const { steps } = buildApp(outRoot, impl);
  assertPipelineOutputs(outRoot, steps);
  const state = await captureState(outRoot);
  assert.equal(state.summary.headline, "Ada Lovelace:11");
  assert.equal(state.chip.text, "chip:mock-dashboard@7");
  assert.deepEqual(state.summary.runtime, {
    hasNodeGlobal: false,
    optionalDebugFlag: true,
    rootKind: "globalThis",
  });
} else if (impl === "both") {
  const jsOut = mkdtempSync(join(tmpdir(), "debundle-impl-e2e-js-"));
  const rustOut = mkdtempSync(join(tmpdir(), "debundle-impl-e2e-rust-"));
  const js = buildApp(jsOut, "js");
  const rust = buildApp(rustOut, "rust");
  assertPipelineOutputs(jsOut, js.steps);
  assertPipelineOutputs(rustOut, rust.steps);
  const [jsState, rustState] = await Promise.all([captureState(jsOut), captureState(rustOut)]);
  assert.deepEqual(rustState, jsState);
} else {
  throw new Error(`Unknown DEBUNDLE_IMPL=${impl}`);
}
