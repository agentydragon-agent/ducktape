import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { parse } from "@babel/parser";
import { analyzeRuntimeBoundaryAst, analyzeRuntimeBoundaryCode } from "../analysis/boundary.mjs";
import { computeJsAsts } from "../common/parse_asts.mjs";
import { getChunk, getChunkEntryFile } from "../common/artifact.mjs";
import { DEFAULT_PARSER_OPTIONS } from "../common/parser_options.mjs";
import { loadJsChunks } from "../common/load_chunks.mjs";
import { normalizeJsChunks } from "../common/normalize.mjs";
import { createWebFixtureRoots, runNodeScript, writeSnapshotFixture } from "../test_support/fixtures.mjs";
import { runTransformSpecObject } from "../transforms/runner.mjs";
import { writeJsTree } from "../transforms/write.mjs";
import { extractAtomicModules } from "./atomic_modules.mjs";
import { materializeLogicalModules } from "./materialize_logical_modules.mjs";
import { mergeModules } from "./merge.mjs";

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

test("mergeModules resolves moduleSelectors by exact member-name sets", async () => {
  const { artifact, selectedOwnerIds, snapshotRoot } = await prepareAtomicFixture("debundle-merge-modules-symbol-selectors-");
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
          moduleSelectors: [
            moduleSelectorForModulePlan(stateBefore.currentModules[0]),
            {
              ...moduleSelectorForModulePlan(stateBefore.currentModules[1]),
              nearbyStructure: {
                nextSymbols: [...stateBefore.currentModules[2].memberNames],
                previousSymbols: [...stateBefore.currentModules[0].memberNames],
              },
              ordinalWindow: {
                end: stateBefore.currentModules[1].startOrdinal,
                start: stateBefore.currentModules[1].startOrdinal,
              },
            },
          ],
          validation: {
            ordered: true,
          },
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

  const { outRoot } = createWebFixtureRoots("debundle-merge-modules-symbol-selectors-write-");
  writeJsTree({
    artifact: merged.artifact,
    force: true,
    outDir: outRoot,
  });

  assert.deepEqual(runNodeScript(join(outRoot, "static", "app", "entry.js")), runNodeScript(join(snapshotRoot, "static", "app.js")));
});

test("mergeModules matches exact selector symbols against the full current member-name set", async () => {
  const { artifact, selectedOwnerIds, snapshotRoot } = await prepareAtomicFixture("debundle-merge-modules-full-set-selectors-");
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
  assert.ok(stateBefore.currentModules.length >= 4);

  const mergedSeedPair = mergeModules({
    artifact: extracted.artifact,
    operations: [
      {
        id: "merge__seed_pair",
        operation: "merge_module",
        selector: {
          chunkId: "static/app",
          moduleIds: [stateBefore.currentModules[0].id, stateBefore.currentModules[1].id],
        },
        target: {
          basename: "seed_pair",
        },
      },
    ],
  });
  const stateAfterSeedPair = getChunk(mergedSeedPair.artifact, "static/app")?.metadata?.moduleExtractionState;
  assert.ok(stateAfterSeedPair);

  const merged = mergeModules({
    artifact: mergedSeedPair.artifact,
    operations: [
      {
        id: "merge__seed_and_first",
        operation: "merge_module",
        selector: {
          chunkId: "static/app",
          moduleSelectors: [
            { symbols: ["readSeed", "seed"] },
            { symbols: ["first"] },
          ],
          validation: {
            ordered: true,
          },
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
  assert.equal(stateAfter.currentModules.length, stateAfterSeedPair.currentModules.length - 1);
  assert.ok(stateAfter.currentModules.some((modulePlan) => modulePlan.id === "merge__seed_and_first"));
  assert.ok(chunk.files.has("modules/seed_and_first.js"));

  const { outRoot } = createWebFixtureRoots("debundle-merge-modules-full-set-selectors-write-");
  writeJsTree({
    artifact: merged.artifact,
    force: true,
    outDir: outRoot,
  });

  assert.deepEqual(runNodeScript(join(outRoot, "static", "app", "entry.js")), runNodeScript(join(snapshotRoot, "static", "app.js")));
});

test("mergeModules resolves representative symbol subsets against the full current member-name set", async () => {
  const { artifact, selectedOwnerIds, snapshotRoot } = await prepareAtomicFixture(
    "debundle-merge-modules-representative-symbol-selectors-"
  );
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
  assert.ok(stateBefore.currentModules.length >= 4);

  const mergedSeedPair = mergeModules({
    artifact: extracted.artifact,
    operations: [
      {
        id: "merge__seed_pair",
        operation: "merge_module",
        selector: {
          chunkId: "static/app",
          moduleIds: [stateBefore.currentModules[0].id, stateBefore.currentModules[1].id],
        },
        target: {
          basename: "seed_pair",
        },
      },
    ],
  });
  const stateAfterSeedPair = getChunk(mergedSeedPair.artifact, "static/app")?.metadata?.moduleExtractionState;
  assert.ok(stateAfterSeedPair);

  const merged = mergeModules({
    artifact: mergedSeedPair.artifact,
    operations: [
      {
        id: "merge__seed_and_first",
        operation: "merge_module",
        selector: {
          chunkId: "static/app",
          moduleSelectors: [
            { symbols: ["seed"] },
            { symbols: ["first"] },
          ],
          validation: {
            ordered: true,
          },
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
  assert.equal(stateAfter.currentModules.length, stateAfterSeedPair.currentModules.length - 1);
  assert.ok(stateAfter.currentModules.some((modulePlan) => modulePlan.id === "merge__seed_and_first"));
  assert.ok(chunk.files.has("modules/seed_and_first.js"));

  const { outRoot } = createWebFixtureRoots("debundle-merge-modules-representative-symbol-selectors-write-");
  writeJsTree({
    artifact: merged.artifact,
    force: true,
    outDir: outRoot,
  });

  assert.deepEqual(runNodeScript(join(outRoot, "static", "app", "entry.js")), runNodeScript(join(snapshotRoot, "static", "app.js")));
});

test("mergeModules ordered selector validation rejects reversed module selector order", async () => {
  const { artifact, selectedOwnerIds } = await prepareAtomicFixture("debundle-merge-modules-selector-order-");
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

  assert.throws(
    () =>
      mergeModules({
        artifact: extracted.artifact,
        operations: [
          {
            id: "merge__seed_and_first",
            operation: "merge_module",
            selector: {
              chunkId: "static/app",
              moduleSelectors: [
                moduleSelectorForModulePlan(stateBefore.currentModules[1]),
                moduleSelectorForModulePlan(stateBefore.currentModules[0]),
              ],
              validation: {
                ordered: true,
              },
            },
            target: {
              basename: "seed_and_first",
            },
          },
        ],
      }),
    /ordered moduleSelectors did not match ascending startOrdinal order/
  );
});

test("mergeModules writes post-merge reports with before/after counts", async () => {
  const { artifact, selectedOwnerIds } = await prepareAtomicFixture("debundle-merge-modules-report-");
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

  const { outRoot } = createWebFixtureRoots("debundle-merge-modules-report-write-");
  const reportOutDir = join(outRoot, "reports");
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
    reportOutDir,
    reportSummaryPath: join(reportOutDir, "summary.json"),
  });

  assert.equal(merged.manifest.kind, "js.merge_module_manifest");
  assert.equal(existsSync(join(reportOutDir, "summary.json")), true);
  assert.equal(existsSync(join(reportOutDir, "static", "app.json")), true);

  const summary = JSON.parse(readFileSync(join(reportOutDir, "summary.json"), "utf8"));
  const chunkReport = JSON.parse(readFileSync(join(reportOutDir, "static", "app.json"), "utf8"));
  assert.equal(summary.counts.chunks, 1);
  assert.equal(summary.counts.mergeOperations, 1);
  assert.equal(summary.counts.modulesBefore, stateBefore.currentModules.length);
  assert.equal(summary.counts.modulesAfter, stateBefore.currentModules.length - 1);
  assert.equal(summary.counts.mergedAway, 1);
  assert.equal(chunkReport.counts.modulesBefore, stateBefore.currentModules.length);
  assert.equal(chunkReport.counts.modulesAfter, stateBefore.currentModules.length - 1);
  assert.deepEqual(chunkReport.operationIds, ["merge__seed_and_first"]);
});

test("merge_remaining_modules folds all unclaimed modules into one residual module", async () => {
  const { artifact, selectedOwnerIds, snapshotRoot } = await prepareAtomicFixture("debundle-merge-remaining-modules-");
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
      {
        id: "merge__unhandled",
        operation: "merge_remaining_modules",
        selector: {
          chunkId: "static/app",
        },
        target: {
          basename: "unhandled",
        },
      },
    ],
  });

  const chunk = getChunk(merged.artifact, "static/app");
  const stateAfter = chunk?.metadata?.moduleExtractionState;
  assert.ok(stateAfter);
  assert.equal(stateAfter.currentModules.length, 2);
  assert.ok(stateAfter.currentModules.some((modulePlan) => modulePlan.id === "merge__seed_and_first"));
  assert.ok(stateAfter.currentModules.some((modulePlan) => modulePlan.id === "merge__unhandled"));
  assert.ok(chunk.files.has("modules/unhandled.js"));

  const { outRoot } = createWebFixtureRoots("debundle-merge-remaining-modules-write-");
  writeJsTree({
    artifact: merged.artifact,
    force: true,
    outDir: outRoot,
  });

  assert.deepEqual(runNodeScript(join(outRoot, "static", "app", "entry.js")), runNodeScript(join(snapshotRoot, "static", "app.js")));
});

test("materializeLogicalModules lowers final logical modules directly from combined ops", async () => {
  const { artifact, snapshotRoot } = await prepareAtomicFixture("debundle-materialize-logical-modules-stage-");
  const operations = logicalModuleOpsForFixture();

  const materialized = materializeLogicalModules({
    artifact,
    chunkIds: ["static/app"],
    operations,
    pruneOtherChunks: false,
  });

  const chunk = getChunk(materialized.artifact, "static/app");
  const state = chunk?.metadata?.moduleExtractionState;
  assert.ok(state);
  assert.equal(state.mode, "logical");
  assert.equal(state.currentModules.length, 3);
  assert.ok(chunk.files.has("modules/seed_state.js"));
  assert.ok(chunk.files.has("modules/first_state.js"));
  assert.ok(chunk.files.has("modules/unhandled.js"));
  assert.equal(materialized.manifest.kind, "js.logical_module_manifest");
  assert.equal(materialized.manifest.counts.explicitLogicalModules, 2);
  assert.equal(materialized.manifest.counts.residualLogicalModules, 1);
  assert.deepEqual(
    materialized.manifest.chunks[0].finalModuleContents.map((modulePlan) => modulePlan.basename),
    ["seed_state", "first_state", "unhandled"]
  );

  const { outRoot } = createWebFixtureRoots("debundle-materialize-logical-modules-stage-write-");
  writeJsTree({
    artifact: materialized.artifact,
    force: true,
    outDir: outRoot,
  });

  const seedModuleCode = readFileSync(join(outRoot, "static", "app", "modules", "seed_state.js"), "utf8");
  const entryCode = readFileSync(join(outRoot, "static", "app", "entry.js"), "utf8");
  assert.match(seedModuleCode, /\bseedValue\b/);
  assert.match(seedModuleCode, /\breadSeedValue\b/);
  assert.doesNotMatch(seedModuleCode, /\bexport let seed\b/);
  assert.match(entryCode, /\bseedValue\b/);
  assert.match(entryCode, /\breadSeedValue\b/);

  assert.deepEqual(runNodeScript(join(outRoot, "static", "app", "entry.js")), runNodeScript(join(snapshotRoot, "static", "app.js")));
});

test("extract_atomic_modules and merge_modules compose in a pipeline spec", async () => {
  const { extractedRoot, outRoot, selectedOwnerIds, snapshotRoot } = await writeAtomicSnapshotFixture(
    "debundle-atomic-modules-pipeline-"
  );
  const previewLoaded = loadJsChunks({
    inputRoot: snapshotRoot,
    jsListPath: join(extractedRoot, "js-files.txt"),
  });
  const previewParsed = computeJsAsts({
    artifact: previewLoaded.artifact,
  });
  const previewNormalized = await normalizeJsChunks({
    artifact: previewParsed.artifact,
    jobs: 1,
  });
  const previewExtracted = extractAtomicModules({
    artifact: previewNormalized.artifact,
    chunkIds: ["static/app"],
    pruneOtherChunks: false,
    selectedOwnerIdsByChunk: {
      "static/app": selectedOwnerIds,
    },
  });
  const previewState = getChunk(previewExtracted.artifact, "static/app")?.metadata?.moduleExtractionState;
  assert.ok(previewState);

  const result = await runTransformSpecObject({
    kind: "js.ast_transform_spec",
    operations: [
      {
        id: "merge__seed_and_first",
        operation: "merge_module",
        selector: {
          chunkId: "static/app",
          moduleSelectors: [
            moduleSelectorForModulePlan(previewState.currentModules[0]),
            moduleSelectorForModulePlan(previewState.currentModules[1]),
          ],
          validation: {
            ordered: true,
          },
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

test("materialize_logical_modules composes directly in a pipeline spec", async () => {
  const { extractedRoot, outRoot, snapshotRoot } = await writeAtomicSnapshotFixture(
    "debundle-logical-modules-pipeline-"
  );
  const result = await runTransformSpecObject({
    kind: "js.ast_transform_spec",
    operations: logicalModuleOpsForFixture(),
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
        id: "logical",
        operation: "materialize_logical_modules",
        args: {
          chunkIds: ["static/app"],
          pruneOtherChunks: false,
        },
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
    ["load_js_chunks", "compute_js_asts", "normalize_js_chunks", "materialize_logical_modules", "write_js_tree"]
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

function moduleSelectorForModulePlan(modulePlan) {
  return {
    symbols: [...modulePlan.memberNames],
  };
}

function logicalModuleOpsForFixture() {
  return [
    {
      id: "logical__seed_state",
      operation: "define_logical_module",
      selector: {
        chunkId: "static/app",
      },
      target: {
        basename: "seed_state",
      },
      members: [
        {
          id: "rename__seed",
          name: "seedValue",
          selector: {
            binding: {
              kind: "VariableDeclarator",
              name: "seed",
            },
          },
        },
        {
          id: "rename__readSeed",
          name: "readSeedValue",
          selector: {
            binding: {
              kind: "FunctionDeclaration",
              name: "readSeed",
            },
          },
        },
      ],
    },
    {
      id: "logical__first_state",
      operation: "define_logical_module",
      selector: {
        chunkId: "static/app",
      },
      target: {
        basename: "first_state",
      },
      members: [
        {
          id: "rename__first",
          name: "firstValue",
          selector: {
            binding: {
              kind: "VariableDeclarator",
              name: "first",
            },
          },
        },
        {
          id: "rename__readFirst",
          name: "readFirstValue",
          selector: {
            binding: {
              kind: "FunctionDeclaration",
              name: "readFirst",
            },
          },
        },
      ],
    },
    {
      id: "logical__unhandled",
      operation: "define_residual_module",
      selector: {
        chunkId: "static/app",
      },
      target: {
        basename: "unhandled",
      },
    },
  ];
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
