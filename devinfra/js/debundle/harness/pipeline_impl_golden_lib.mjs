import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { runMockBrowserBundlePipeline } from "./mock_pipeline.mjs";
import { createMockBrowserBundleTransformSpec } from "./mock_spec.mjs";

const FIXTURE_ROOT = fileURLToPath(new URL("./testdata/mock_browser_bundle/", import.meta.url));

export async function buildJsGolden(outRoot) {
  const { appRoot } = await runMockBrowserBundlePipeline({ prefix: "debundle-impl-golden-js-" });
  copyTree(appRoot, outRoot);
}

export function buildRustGolden(outRoot, rustBin) {
  const generatedRoot = join(FIXTURE_ROOT, "generated");
  const snapshotRoot = join(generatedRoot, "snapshot");
  const extractedRoot = join(generatedRoot, "extracted");
  const specPath = join(mkdtempSync(join(tmpdir(), "debundle-rust-spec-")), "transform-spec.json");
  writeMockSpec(specPath, outRoot, snapshotRoot, extractedRoot);
  const run = spawnSync(rustBin, ["--spec", specPath], { encoding: "utf8" });
  if (run.status !== 0) {
    throw new Error(`debundle_rust failed:\nstdout:\n${run.stdout}\nstderr:\n${run.stderr}`);
  }
  cpSync(join(snapshotRoot, "preload"), join(outRoot, "preload"), { recursive: true });
}

export function writeMockSpec(specPath, outRoot, snapshotRoot, extractedRoot) {
  const spec = createMockBrowserBundleTransformSpec({
    appRoot: outRoot,
    assetSummaryPath: join(extractedRoot, "asset-summary.json"),
    jsListPath: join(extractedRoot, "js-files.txt"),
    snapshotRoot,
  });
  writeFileSync(specPath, `${JSON.stringify(spec, null, 2)}\n`);
}

export const writeMockRustSpec = writeMockSpec;

export function computeDiffSummary(jsRoot, rustRoot) {
  const jsFiles = listFiles(jsRoot).filter((f) => !isTransientPath(f));
  const rustFiles = listFiles(rustRoot).filter((f) => !isTransientPath(f));
  const onlyJs = jsFiles.filter((f) => !rustFiles.includes(f));
  const onlyRust = rustFiles.filter((f) => !jsFiles.includes(f));
  const common = jsFiles.filter((f) => rustFiles.includes(f));
  const changed = common.filter(
    (f) =>
      normalizedForDiff(readFileSync(join(jsRoot, f), "utf8"), f) !==
      normalizedForDiff(readFileSync(join(rustRoot, f), "utf8"), f)
  );
  return [
    "# JS vs Rust golden diff summary",
    `only_js: ${onlyJs.length}`,
    ...onlyJs.map((f) => `  - ${f}`),
    `only_rust: ${onlyRust.length}`,
    ...onlyRust.map((f) => `  - ${f}`),
    `changed: ${changed.length}`,
    ...changed.map((f) => `  - ${f}`),
    "",
  ].join("\n");
}

function isTransientPath(path) {
  return (
    /^static\/[^/]+\/(entry\.js|manifest\.json)$/.test(path) ||
    path === "planner_snapshot.json" ||
    path === "analysis_snapshot.json"
  );
}

function normalizedForDiff(text, rel) {
  if (rel !== "manifest.json") {
    return text;
  }
  try {
    const parsed = JSON.parse(text);
    if (parsed?.schemaVersion === 1 && parsed?.scriptSource === "split") {
      parsed.sourceHtml = "__PIPELINE_ROOT__/snapshot/index.html";
      parsed.snapshotRoot = "__PIPELINE_ROOT__/snapshot";
      parsed.assetSummaryPath = "__PIPELINE_ROOT__/extracted/asset-summary.json";
      parsed.chunksManifestPath = "__PIPELINE_ROOT__/app/chunks.manifest.json";
      parsed.runtimeRoot = "__PIPELINE_ROOT__/app";
      parsed.outDir = "__PIPELINE_ROOT__/app";
      if (parsed.generated) {
        parsed.generated.bootstrap = "__PIPELINE_ROOT__/app/bootstrap.js";
        parsed.generated.chunksManifest = "__PIPELINE_ROOT__/app/chunks.manifest.json";
        parsed.generated.indexHtml = "__PIPELINE_ROOT__/app/index.html";
      }
      return JSON.stringify(parsed, null, 2) + "\n";
    }
  } catch {
    return text;
  }
  return text;
}

export function copyTree(src, dst) {
  rmSync(dst, { recursive: true, force: true });
  mkdirSync(dst, { recursive: true });
  cpSync(src, dst, { recursive: true });
}

export function listFiles(root) {
  const out = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else {
        out.push(relative(root, full).replaceAll("\\", "/"));
      }
    }
  };
  walk(root);
  return out.sort();
}
