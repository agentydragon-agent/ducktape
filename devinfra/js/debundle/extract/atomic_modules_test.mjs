import assert from "node:assert/strict";
import { join } from "node:path";
import test from "node:test";
import { parse } from "@babel/parser";
import { analyzeRuntimeBoundaryAst, analyzeRuntimeBoundaryCode } from "../analysis/runtime_boundary_metadata_lib.mjs";
import { computeJsAsts } from "../common/compute_js_asts_lib.mjs";
import { getChunk, getChunkEntryFile } from "../common/pipeline_artifact_lib.mjs";
import { DEFAULT_PARSER_OPTIONS } from "../common/js_module_lib.mjs";
import { loadJsChunks } from "../common/load_js_chunks_lib.mjs";
import { normalizeJsChunks } from "../split/split_js_tree_lib.mjs";
import { createWebFixtureRoots, runNodeScript, writeSnapshotFixture } from "../test_support/fixture_lib.mjs";
import { runTransformSpecObject } from "../transforms/run_transform_lib.mjs";
import { writeJsTree } from "../transforms/write_js_tree_lib.mjs";
import { extractAtomicModules } from "./atomic_modules_stage_lib.mjs";
import { mergeModules } from "./merge_modules_stage_lib.mjs";

test("extractAtomicModules emits one module per atomic unit and preserves behavior", async () => {
  const { artifact, selectedOwnerIds, snapshotRoot } = await prepareAtomicFixture("debundle-atomic-modules-stage-");

  const result = extractAtomicModules({
    artifact,
    chunkIds: ["static/app"],
    pruneOtherChunks: false,
    selectedOwnerIdsByChunk: {
      "static/app": selectedOwnerIds,
    },
  });

  const chunk = getChunk(result.artifact, "static/app");
  const state = chunk?.metadata?.moduleExtractionState;
  assert.equal(result.manifest.kind, "js.atomic_module_manifest");
  assert.ok(state);
  assert.equal(state.kind, "js.module_extraction_state");
  assert.equal(state.currentModules.length, state.atomicUnits.length);
  assert.ok(state.currentModules.length > 1);
  assert.deepEqual(
    state.currentModules.map((modulePlan) => modulePlan.unitIds),
    state.currentModules.map((modulePlan) => [modulePlan.id.replace(/^atomic_module_/, "selected_atomic_unit_")])
  );
  assert.equal(
    [...chunk.files.keys()].filter((file) => file.startsWith("modules/")).length,
    state.currentModules.length
  );

  const { outRoot } = createWebFixtureRoots("debundle-atomic-modules-stage-write-");
  writeJsTree({
    artifact: result.artifact,
    force: true,
    outDir: outRoot,
  });

  assert.deepEqual(runNodeScript(join(outRoot, "static", "app", "entry.js")), runNodeScript(join(snapshotRoot, "static", "app.js")));
});

test("mergeModules merges selected extracted modules and preserves behavior", async () => {
  const { artifact, selectedOwnerIds, snapshotRoot } = await prepareAtomicFixture("debundle-merge-modules-stage-");
  const extracted = extractAtomicModules({
    artifact,
    chunkIds: ["static/app"],
    pruneOtherChunks: false,
    selectedOwnerIdsByChunk: {
      "static/app": selectedOwnerIds,
    },
  });
  const stateBefore = getChunk(extracted.artifact, "static/app")?.metadata?.moduleExtractionState;
  assert.ok(stateBefore);
  assert.ok(stateBefore.currentModules.length >= 3);

  const merged = mergeModules({
    artifact: extracted.artifact,
    operations: [
      {
        id: "merge__seed_and_first",
        operation: "merge_module",
        selector: {
          chunkId: "static/app",
          moduleIds: [stateBefore.currentModules[0].id, stateBefore.currentModules[1].id],
        },
        target: {
          basename: "seed_and_first",
        },
      },
    ],
  });

  const chunk = getChunk(merged.artifact, "static/app");
  const stateAfter = chunk?.metadata?.moduleExtractionState;
  assert.ok(stateAfter);
  assert.equal(stateAfter.currentModules.length, stateBefore.currentModules.length - 1);
  assert.ok(stateAfter.currentModules.some((modulePlan) => modulePlan.id === "merge__seed_and_first"));
  assert.ok(chunk.files.has("modules/seed_and_first.js"));

  const { outRoot } = createWebFixtureRoots("debundle-merge-modules-stage-write-");
  writeJsTree({
    artifact: merged.artifact,
    force: true,
    outDir: outRoot,
  });

  assert.deepEqual(runNodeScript(join(outRoot, "static", "app", "entry.js")), runNodeScript(join(snapshotRoot, "static", "app.js")));
});

test("extract_atomic_modules and merge_modules compose in a pipeline spec", async () => {
  const { extractedRoot, outRoot, selectedOwnerIds, snapshotRoot } = await writeAtomicSnapshotFixture(
    "debundle-atomic-modules-pipeline-"
  );
  const result = await runTransformSpecObject({
    kind: "js.ast_transform_spec",
    operations: [
      {
        id: "merge__seed_and_first",
        operation: "merge_module",
        selector: {
          chunkId: "static/app",
          moduleIds: ["atomic_module_0000", "atomic_module_0001"],
        },
        target: {
          basename: "seed_and_first",
        },
      },
    ],
    pipeline: [
      {
        id: "load",
        operation: "load_js_chunks",
        args: {
          inputRoot: snapshotRoot,
          jsListPath: join(extractedRoot, "js-files.txt"),
        },
      },
      {
        id: "asts",
        operation: "compute_js_asts",
      },
      {
        id: "normalize",
        operation: "normalize_js_chunks",
        args: {
          jobs: 1,
        },
      },
      {
        id: "extract",
        operation: "extract_atomic_modules",
        args: {
          chunkIds: ["static/app"],
          pruneOtherChunks: false,
          selectedOwnerIdsByChunk: {
            "static/app": selectedOwnerIds,
          },
        },
      },
      {
        id: "merge",
        operation: "merge_modules",
      },
      {
        id: "write",
        operation: "write_js_tree",
        args: {
          force: true,
          outDir: outRoot,
        },
      },
    ],
  });

  assert.deepEqual(
    result.steps.map((step) => step.operation),
    [
      "load_js_chunks",
      "compute_js_asts",
      "normalize_js_chunks",
      "extract_atomic_modules",
      "merge_modules",
      "write_js_tree",
    ]
  );
  assert.deepEqual(runNodeScript(join(outRoot, "static", "app", "entry.js")), runNodeScript(join(snapshotRoot, "static", "app.js")));
});

async function prepareAtomicFixture(prefix) {
  const { extractedRoot, selectedOwnerIds, snapshotRoot } = await writeAtomicSnapshotFixture(prefix);
  const loaded = loadJsChunks({
    inputRoot: snapshotRoot,
    jsListPath: join(extractedRoot, "js-files.txt"),
  });
  const parsed = computeJsAsts({
    artifact: loaded.artifact,
  });
  const normalized = await normalizeJsChunks({
    artifact: parsed.artifact,
    jobs: 1,
  });
  return {
    artifact: normalized.artifact,
    selectedOwnerIds,
    snapshotRoot,
  };
}

async function writeAtomicSnapshotFixture(prefix) {
  const { extractedRoot, outRoot, snapshotRoot } = createWebFixtureRoots(prefix);
  const source = fixtureSource();
  writeSnapshotFixture({
    extractedRoot,
    files: {
      "static/app.js": source,
    },
    jsFiles: ["static/app.js"],
    snapshotRoot,
  });

  const loaded = loadJsChunks({
    inputRoot: snapshotRoot,
    jsListPath: join(extractedRoot, "js-files.txt"),
  });
  const parsed = computeJsAsts({
    artifact: loaded.artifact,
  });
  const normalized = await normalizeJsChunks({
    artifact: parsed.artifact,
    jobs: 1,
  });
  const runtimeFile = getChunkEntryFile(normalized.artifact, "static/app");
  const analysis = analyzeRuntimeBoundaryAst(runtimeFile.ast, {
    chunkId: "static/app",
    manifestPath: "static/app/manifest.json",
    runtimePath: "static/app/entry.js",
    uiVersion: "fixture",
  });
  const selectedOwnerIds = ownerIdsForNames(analysis, ["seed", "readSeed", "first", "readFirst", "second", "render"]);

  return {
    extractedRoot,
    outRoot,
    selectedOwnerIds,
    snapshotRoot,
  };
}

function ownerIdsForNames(analysis, names) {
  return names.map((name) => {
    const ownerId = analysis.owners.find((owner) => owner.names.includes(name))?.id;
    assert.ok(ownerId, `missing owner ${name}`);
    return ownerId;
  });
}

function fixtureSource() {
  const source = `const seed = 1;
function readSeed() {
  return seed;
}

console.log("atomic-barrier-0");

const first = readSeed() + 1;
function readFirst() {
  return first;
}

console.log("atomic-barrier-1");

const second = readFirst() + 1;
function render() {
  return \`second=\${second}\`;
}

console.log(render());

export { first, readFirst, render, second };
`;
  parse(source, DEFAULT_PARSER_OPTIONS);
  analyzeRuntimeBoundaryCode(source, {
    ast: parse(source, DEFAULT_PARSER_OPTIONS),
    chunkId: "static/app",
    runtimePath: "fixture/runtime.js",
    uiVersion: "fixture",
  });
  return source;
}
