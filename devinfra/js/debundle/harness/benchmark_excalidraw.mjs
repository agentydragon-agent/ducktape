#!/usr/bin/env node
// Debundler benchmark on the Excalidraw bundle.
//
// Pipeline: load_js_chunks -> compute_js_asts -> normalize_js_chunks ->
//           materialize_logical_modules.
//
// The benchmark synthesizes a small set of `define_logical_module` operations
// by first planning atomic modules on the largest chunk and then grouping
// consecutive atomic modules into pairwise logical modules. This keeps the
// benchmark aligned with the current first-party materialization path while
// still exercising non-trivial module regrouping work.

import { mkdtempSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { Session } from "node:inspector/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { analyzeRuntimeBoundaryAst } from "../analysis/boundary.mjs";
import { getArtifactManifest, getChunkEntryFile, listChunkIds } from "../common/artifact.mjs";
import { computeJsAsts } from "../common/parse_asts.mjs";
import { loadJsChunks } from "../common/load_chunks.mjs";
import { normalizeJsChunks } from "../common/normalize.mjs";
import { materializeLogicalModules } from "../extract/materialize_logical_modules.mjs";
import { planSelectedAtomicModules } from "../extract/planner.mjs";

const DEFAULT_FIXTURE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "excalidraw_bundle_assets");
const DEFAULT_MODULE_COUNT = 20;

async function main() {
  const { cpuProfilePath, fixtureDir, moduleCount } = parseArgs(process.argv.slice(2));
  const jsListPath = writeJsListForFixtureDir(fixtureDir);

  const profilerSession = cpuProfilePath ? new Session() : null;
  if (profilerSession) {
    profilerSession.connect();
    await profilerSession.post("Profiler.enable");
    await profilerSession.post("Profiler.setSamplingInterval", { interval: 100 });
    await profilerSession.post("Profiler.start");
  }

  const totalStartedAt = process.hrtime.bigint();
  const stageTimings = [];
  let artifact;

  artifact = await timeStage("load_js_chunks", stageTimings, () =>
    loadJsChunks({ inputRoot: fixtureDir, jsListPath })
  );
  artifact = await timeStage("compute_js_asts", stageTimings, () => computeJsAsts({ artifact }));
  artifact = await timeStage("normalize_js_chunks", stageTimings, () => normalizeJsChunks({ artifact }));

  const entryChunkId = pickChunkWithMostTopLevelBindings(artifact);
  const operations = buildPairLogicalModuleOperations(artifact, entryChunkId, moduleCount);
  artifact = await timeStage(`materialize_logical_modules x${operations.length}`, stageTimings, () =>
    materializeLogicalModules({
      artifact,
      chunkIds: [entryChunkId],
      operations,
      pruneOtherChunks: false,
      targetDir: "bench",
    })
  );

  const totalDurationMs = nsToMs(process.hrtime.bigint() - totalStartedAt);

  if (profilerSession) {
    const { profile } = await profilerSession.post("Profiler.stop");
    writeFileSync(cpuProfilePath, JSON.stringify(profile));
    await profilerSession.post("Profiler.disable");
    profilerSession.disconnect();
    process.stdout.write(`cpu profile written to ${cpuProfilePath}\n`);
  }

  reportResults({ chunkId: entryChunkId, operations, stageTimings, totalDurationMs });
}

function parseArgs(argv) {
  const result = {
    cpuProfilePath: null,
    fixtureDir: DEFAULT_FIXTURE_DIR,
    moduleCount: DEFAULT_MODULE_COUNT,
  };
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (arg === "--fixture-dir") {
      result.fixtureDir = resolve(requireValue(argv, ++index, arg));
    } else if (arg === "--modules") {
      result.moduleCount = parseModuleCount(requireValue(argv, ++index, arg));
    } else if (arg === "--cpu-profile") {
      result.cpuProfilePath = resolve(requireValue(argv, ++index, arg));
    } else if (arg === "--help" || arg === "-h") {
      printUsage();
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return result;
}

function writeJsListForFixtureDir(fixtureDir) {
  const entries = readdirSync(fixtureDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".js"))
    .map((entry) => ({ name: entry.name, size: statSync(join(fixtureDir, entry.name)).size }))
    .sort((left, right) => right.size - left.size);
  if (entries.length === 0) {
    throw new Error(`No .js files found under ${fixtureDir}`);
  }
  const tmp = mkdtempSync(join(tmpdir(), "benchmark_excalidraw-"));
  const jsListPath = join(tmp, "js-files.txt");
  writeFileSync(jsListPath, `${entries[0].name}\n`);
  return jsListPath;
}

function requireValue(argv, index, flag) {
  const value = argv[index];
  if (!value || value.startsWith("--")) {
    throw new Error(`${flag} requires a value`);
  }
  return value;
}

function parseModuleCount(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error(`--modules must be a positive integer, got ${value}`);
  }
  return parsed;
}

function printUsage() {
  process.stdout.write(`Usage:
  benchmark_excalidraw [--fixture-dir DIR] [--modules N]

Defaults: --fixture-dir ${DEFAULT_FIXTURE_DIR}
          --modules ${DEFAULT_MODULE_COUNT}
`);
}

async function timeStage(label, timings, runStage) {
  const startedAt = process.hrtime.bigint();
  const result = await runStage();
  const durationMs = nsToMs(process.hrtime.bigint() - startedAt);
  timings.push({ label, durationMs });
  process.stdout.write(`stage ${label} ${durationMs.toFixed(1)}ms\n`);
  return result.artifact;
}

function pickChunkWithMostTopLevelBindings(artifact) {
  let bestChunkId = null;
  let bestBindings = -1;
  for (const chunkId of listChunkIds(artifact)) {
    const bindings = artifact.extras?.chunkManifests?.[chunkId]?.counts?.topLevelBindings ?? 0;
    if (bindings > bestBindings) {
      bestBindings = bindings;
      bestChunkId = chunkId;
    }
  }
  if (!bestChunkId) {
    throw new Error("No chunks loaded");
  }
  return bestChunkId;
}

function buildPairLogicalModuleOperations(artifact, chunkId, moduleCount) {
  const runtimeFile = getChunkEntryFile(artifact, chunkId);
  if (!runtimeFile?.ast) {
    throw new Error(`Missing entry AST for benchmark chunk ${chunkId}`);
  }
  const artifactManifest = getArtifactManifest(artifact);
  const analysis = analyzeRuntimeBoundaryAst(runtimeFile.ast, {
    chunkId,
    manifestPath: `${chunkId}/manifest.json`,
    runtimePath: `${chunkId}/${runtimeFile.path}`,
    uiVersion: artifactManifest?.uiVersion ?? null,
  });
  const atomicPlan = planSelectedAtomicModules(
    {
      analysis,
      code: null,
      programBody: runtimeFile.ast.program.body,
    },
    {}
  );

  const ownerById = new Map(analysis.owners.map((owner) => [owner.id, owner]));
  const operations = [];
  for (let pairIndex = 0; pairIndex < moduleCount; pairIndex++) {
    const left = atomicPlan.modulePlans[pairIndex * 2];
    const right = atomicPlan.modulePlans[pairIndex * 2 + 1];
    if (!left || !right) {
      break;
    }
    const selectedModules = [left, right];
    operations.push({
      id: `bench_logical_${pairIndex.toString().padStart(3, "0")}`,
      operation: "define_logical_module",
      selector: { chunkId },
      target: { path: `bench/${pairIndex.toString().padStart(3, "0")}` },
      members: selectedModules.map((modulePlan, moduleIndex) =>
        createAnchorMember(modulePlan, ownerById, pairIndex, moduleIndex)
      ),
    });
  }
  if (operations.length === 0) {
    throw new Error(`No logical module operations could be synthesized (modulePlans=${atomicPlan.modulePlans.length})`);
  }
  return operations;
}

function createAnchorMember(modulePlan, ownerById, pairIndex, moduleIndex) {
  const owner = ownerById.get(modulePlan.ownerIds[0]) ?? null;
  const sourceName = owner?.names?.[0] ?? modulePlan.memberNames[0];
  if (!sourceName) {
    throw new Error(`Could not derive anchor member for ${modulePlan.id}`);
  }
  return {
    id: `bench_member_${pairIndex.toString().padStart(3, "0")}_${moduleIndex.toString().padStart(2, "0")}`,
    name: sourceName,
    selector: {
      binding: {
        kind: owner ? selectorBindingKindForOwnerType(owner.type) : null,
        name: sourceName,
      },
      ...(owner ? { owner: { id: owner.id } } : {}),
    },
  };
}

function selectorBindingKindForOwnerType(ownerType) {
  if (ownerType === "VariableDeclaration") {
    return "VariableDeclarator";
  }
  return ownerType;
}

function reportResults({ chunkId, operations, stageTimings, totalDurationMs }) {
  process.stdout.write("\n=== benchmark_excalidraw results ===\n");
  process.stdout.write(`chunk: ${chunkId}\n`);
  process.stdout.write(`logical modules: ${operations.length}\n`);
  for (const { label, durationMs } of stageTimings) {
    process.stdout.write(`  ${label.padEnd(36)} ${durationMs.toFixed(1)}ms\n`);
  }
  process.stdout.write(`total: ${totalDurationMs.toFixed(1)}ms\n`);
}

function nsToMs(bigintNanoseconds) {
  return Number(bigintNanoseconds) / 1_000_000;
}

await main();
