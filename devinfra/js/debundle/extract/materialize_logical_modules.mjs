import { readFileSync } from "node:fs";
import { join, posix } from "node:path";
import * as t from "@babel/types";
import { analyzeRuntimeBoundaryAst } from "../analysis/boundary.mjs";
import { DEFAULT_PARSER_OPTIONS, writeJsonFile } from "../common/parser_options.mjs";
import {
  createChunk,
  createFile,
  deleteArtifactChunkManifest,
  getArtifactChunkManifest,
  getArtifactManifest,
  getChunk,
  getChunkEntryFile,
  getChunkEntryPath,
  getChunkFile,
  removeFiles,
  requirePipelineArtifact,
  setArtifactChunkManifest,
  setArtifactManifest,
  setChunk,
} from "../common/artifact.mjs";
import {
  formatDurationSince,
  logProgress,
  prepareOutputDir,
  relativeWorkspacePath,
  resolveWorkspacePath,
} from "../common/io.mjs";
import { buildSelectedModuleLoweringMetadata, extractSelectedModulePlanInAst } from "./init_region.mjs";
import { buildLogicalModulePlans } from "./logical_modules.mjs";
import { deriveSelectedModuleTarget, planSelectedAtomicModules } from "./planner.mjs";

export function materializeLogicalModules({
  artifact,
  boundaryAnalysisDir = undefined,
  chunkIds,
  file = undefined,
  pruneOtherChunks = true,
  force = false,
  operations = [],
  reportOutDir = undefined,
  reportSummaryPath = undefined,
  selectedOwnerIdsByChunk = undefined,
  targetDir = "modules",
}) {
  requirePipelineArtifact(artifact, "materializeLogicalModules");
  let artifactManifest = getArtifactManifest(artifact);
  if (!Array.isArray(artifactManifest?.chunks)) {
    throw new Error("materializeLogicalModules requires an artifact manifest in artifact extras");
  }

  const selectedChunkIds = normalizeChunkIds(chunkIds);
  const startedAt = process.hrtime.bigint();
  const resolvedBoundaryAnalysisDir = boundaryAnalysisDir ? resolveWorkspacePath(boundaryAnalysisDir) : null;
  const reports = [];
  const applied = [];

  let resolvedReportOutDir = null;
  let resolvedReportSummaryPath = null;
  if (reportOutDir) {
    resolvedReportOutDir = resolveWorkspacePath(reportOutDir);
    prepareOutputDir(resolvedReportOutDir, { force });
    resolvedReportSummaryPath = resolveWorkspacePath(reportSummaryPath ?? posix.join(reportOutDir, "summary.json"));
  }

  if (pruneOtherChunks) {
    pruneArtifactToChunkIds(artifact, selectedChunkIds);
    artifactManifest = getArtifactManifest(artifact);
  }

  logProgress(`logical-modules start chunks=${selectedChunkIds.length}`);

  for (const chunkId of selectedChunkIds) {
    const targetFile = file ? normalizeRelativeFile(file) : getChunkEntryPath(artifact, chunkId);
    if (!targetFile) {
      throw new Error(`materializeLogicalModules could not determine entry file for chunk: ${chunkId}`);
    }
    const runtimeFile = file ? getChunkFile(artifact, chunkId, targetFile) : getChunkEntryFile(artifact, chunkId);
    if (!runtimeFile?.ast) {
      throw new Error(`materializeLogicalModules missing entry AST for chunk: ${chunkId}`);
    }

    const runtimeHeaderLines = runtimeFile.headerLines ?? [];
    const runtimeParserOptions = runtimeFile.parserOptions ?? DEFAULT_PARSER_OPTIONS;
    const chunkStartedAt = process.hrtime.bigint();
    const analysisStartedAt = process.hrtime.bigint();
    const analysis =
      resolvedBoundaryAnalysisDir
        ? readBoundaryAnalysis(join(resolvedBoundaryAnalysisDir, `${chunkId}.json`))
        : analyzeRuntimeBoundaryAst(runtimeFile.ast, {
            chunkId,
            manifestPath: `${chunkId}/manifest.json`,
            runtimePath: `${chunkId}/${targetFile}`,
            uiVersion: artifactManifest?.uiVersion ?? null,
          });
    const analysisMs = durationMsSince(analysisStartedAt);
    const planningStartedAt = process.hrtime.bigint();
    const atomicPlan = planSelectedAtomicModules(
      {
        analysis,
        code: null,
        programBody: runtimeFile.ast.program.body,
      },
      {
        selectedOwnerIds: selectedOwnerIdsByChunk?.[chunkId] ?? null,
      }
    );
    const planningMs = durationMsSince(planningStartedAt);

    const atomicModules = atomicPlan.modulePlans.map((modulePlan, index) => {
      const target = deriveSelectedModuleTarget(modulePlan, index, { targetDir });
      return {
        ...cloneModulePlan(modulePlan),
        initName: target.init,
        targetFile: target.file,
      };
    });
    const logicalModules = buildLogicalModulePlans(atomicModules, operations, { analysis, chunkId, targetDir });

    const parseStartedAt = process.hrtime.bigint();
    const loweringAst = t.cloneNode(runtimeFile.ast, true);
    const parseMs = durationMsSince(parseStartedAt);
    const loweringStartedAt = process.hrtime.bigint();
    const result = extractSelectedModulePlanInAst(
      loweringAst,
      {
        kind: "js.selected_module_plan",
        modulePlans: logicalModules.modules,
      },
      {
        analysis,
        chunkId,
        file: targetFile,
        headerLines: runtimeHeaderLines,
        idPrefix: "logical_module",
        targetDir,
      }
    );
    const loweringMs = durationMsSince(loweringStartedAt);

    const moduleByTargetFile = new Map(logicalModules.modules.map((modulePlan) => [modulePlan.targetFile, modulePlan]));
    const chunk = getChunk(artifact, chunkId);
    const writebackStartedAt = process.hrtime.bigint();
    const nextChunk = createChunk({
      chunkId,
      entryFile: targetFile,
      files: [...result.jsFiles.entries()].map(([relativePath, fileArtifact]) => {
        const modulePlan = moduleByTargetFile.get(relativePath) ?? null;
        return createFile({
          path: relativePath,
          ast: fileArtifact.ast,
          headerLines: fileArtifact.headerLines,
          metadata: {
            ...(runtimeFile.metadata ?? {}),
            chunkFile: relativePath,
            chunkId,
            role: relativePath === targetFile ? "entry" : "module",
            ...(relativePath === targetFile ? {} : { generated: buildSelectedModuleLoweringMetadata() }),
            ...(modulePlan
              ? {
                  moduleExtraction: {
                    id: modulePlan.id,
                    kind: "logical",
                    nameHint: modulePlan.nameHint,
                    ownerIds: [...modulePlan.ownerIds],
                    unitIds: [...modulePlan.unitIds],
                  },
                }
              : {}),
          },
          parserOptions: runtimeParserOptions,
        });
      }),
      metadata: {
        ...(chunk?.metadata ?? {}),
        moduleExtractionState: {
          analysis,
          atomicUnits: atomicPlan.atomicUnits.map(cloneAtomicUnit),
          currentModules: logicalModules.modules.map(cloneModulePlan),
          headerLines: [...runtimeHeaderLines],
          kind: "js.module_extraction_state",
          mode: "logical",
          originalAst: runtimeFile.ast,
          parserOptions: runtimeParserOptions,
          runtimeFile: targetFile,
          sourceAtomicModules: atomicModules.map(cloneModulePlan),
          targetDir: normalizeRelativeFile(targetDir),
        },
      },
    });
    setChunk(artifact, nextChunk);
    const writebackMs = durationMsSince(writebackStartedAt);

    const chunkManifest = getArtifactChunkManifest(artifact, chunkId);
    setArtifactChunkManifest(artifact, chunkId, {
      ...chunkManifest,
      entryFile: targetFile,
      logicalModules: {
        count: logicalModules.modules.length,
        moduleIds: logicalModules.modules.map((modulePlan) => modulePlan.id),
        targetDir: normalizeRelativeFile(targetDir),
      },
      selectedModuleLowerings: result.applied,
    });

    const finalModules = logicalModules.modules.map((modulePlan) => ({
      file: modulePlan.targetFile,
      id: modulePlan.id,
      memberNames: [...modulePlan.memberNames],
      path: modulePlan.modulePath,
      ownerIds: [...modulePlan.ownerIds],
      startOrdinal: modulePlan.startOrdinal,
      unitIds: [...modulePlan.unitIds],
    }));
    const report = {
      chunkId,
      counts: {
        applied: result.applied.length,
        atomicModules: atomicModules.length,
        atomicUnits: atomicPlan.atomicUnitCount,
        explicitLogicalModules: logicalModules.counts.explicitModules,
        finalModules: logicalModules.counts.totalModules,
        residualLogicalModules: logicalModules.counts.residualModules,
        selectedOwners: atomicPlan.selectedOwnerCount,
        unmatchedMembers: logicalModules.counts.unmatchedMembers,
      },
      finalModuleContents: finalModules,
      requestedLogicalModules: logicalModules.reports,
      timingsMs: {
        analysis: analysisMs,
        ...(atomicPlan.timingsMs
          ? {
              planBuildAtomicUnits: atomicPlan.timingsMs.buildAtomicUnits,
              planFinalizeAtomicUnits: atomicPlan.timingsMs.finalizeAtomicUnits,
              planFinalizeModules: atomicPlan.timingsMs.finalizeModules,
              planSelectOwners: atomicPlan.timingsMs.selectOwners,
            }
          : {}),
        lower: loweringMs,
        parseLoweringAst: parseMs,
        plan: planningMs,
        total: durationMsSince(chunkStartedAt),
        writeback: writebackMs,
      },
    };
    reports.push(report);
    applied.push(...result.applied);
    if (resolvedReportOutDir) {
      writeJsonFile(join(resolvedReportOutDir, `${chunkId}.json`), report);
    }
    logProgress(
      `logical-modules chunk=${chunkId} final=${logicalModules.modules.length} explicit=${logicalModules.counts.explicitModules} residual=${logicalModules.counts.residualModules} analysis=${formatDuration(
        analysisMs
      )} plan=${formatDuration(planningMs)} parse=${formatDuration(parseMs)} lower=${formatDuration(
        loweringMs
      )} writeback=${formatDuration(writebackMs)} total=${formatDuration(report.timingsMs.total)}`
    );
  }

  setArtifactManifest(artifact, {
    ...artifactManifest,
    counts: {
      ...(artifactManifest?.counts ?? {}),
      selectedModuleLowerings: applied.length,
    },
    logicalModules: {
      chunkCount: reports.length,
      moduleCount: reports.reduce((sum, report) => sum + report.counts.finalModules, 0),
    },
    selectedModuleLowerings: applied,
  });

  const manifest = {
    chunkCount: reports.length,
    chunks: reports,
    counts: {
      applied: applied.length,
      finalModules: reports.reduce((sum, report) => sum + report.counts.finalModules, 0),
      explicitLogicalModules: reports.reduce((sum, report) => sum + report.counts.explicitLogicalModules, 0),
      residualLogicalModules: reports.reduce((sum, report) => sum + report.counts.residualLogicalModules, 0),
    },
    durationMs: Number(process.hrtime.bigint() - startedAt) / 1_000_000,
    kind: "js.logical_module_manifest",
    reportOutDir: resolvedReportOutDir ? relativeWorkspacePath(resolvedReportOutDir) : null,
    schemaVersion: 1,
  };
  if (resolvedReportSummaryPath) {
    writeJsonFile(resolvedReportSummaryPath, manifest);
  }

  logProgress(
    `logical-modules done chunks=${reports.length} modules=${manifest.counts.finalModules} duration=${formatDurationSince(startedAt)}`
  );
  return {
    artifact,
    manifest,
  };
}

function cloneAtomicUnit(unit) {
  return {
    attachedItemIds: [...unit.attachedItemIds],
    ...(unit.bytes === null ? { bytes: null } : { bytes: unit.bytes }),
    id: unit.id,
    index: unit.index,
    lines: unit.lines,
    memberNames: [...unit.memberNames],
    ownerIds: [...unit.ownerIds],
    startOrdinal: unit.startOrdinal,
  };
}

function cloneModulePlan(modulePlan) {
  return {
    attachedItemIds: [...modulePlan.attachedItemIds],
    ...(modulePlan.bytes === null ? { bytes: null } : { bytes: modulePlan.bytes }),
    id: modulePlan.id,
    index: modulePlan.index,
    ...(modulePlan.initName ? { initName: modulePlan.initName } : {}),
    lines: modulePlan.lines,
    memberNames: [...modulePlan.memberNames],
    modulePath: modulePlan.modulePath,
    nameHint: modulePlan.nameHint,
    ownerIds: [...modulePlan.ownerIds],
    ...(Array.isArray(modulePlan.bindingPlacements)
      ? {
          bindingPlacements: modulePlan.bindingPlacements.map((entry) => ({ ...entry })),
        }
      : {}),
    ...(Array.isArray(modulePlan.requestedBindings)
      ? {
          requestedBindings: modulePlan.requestedBindings.map((binding) => ({ ...binding })),
        }
      : {}),
    startOrdinal: modulePlan.startOrdinal,
    ...(modulePlan.targetFile ? { targetFile: modulePlan.targetFile } : {}),
    unitIds: [...modulePlan.unitIds],
  };
}

function normalizeChunkIds(chunkIds) {
  if (!Array.isArray(chunkIds) || chunkIds.length === 0) {
    throw new Error("materializeLogicalModules requires at least one chunkId");
  }
  return [...new Set(chunkIds.map(normalizeRelativeFile))];
}

function normalizeRelativeFile(value) {
  if (typeof value !== "string" || value === "") {
    throw new Error(`Expected a non-empty relative path, got: ${value}`);
  }
  const normalized = posix.normalize(value.split("\\").join("/"));
  if (normalized === "." || normalized.startsWith("/") || normalized.split("/").includes("..")) {
    throw new Error(`Invalid relative path: ${value}`);
  }
  return normalized;
}

function pruneArtifactToChunkIds(artifact, chunkIds) {
  const selectedChunkIds = new Set(chunkIds);
  removeFiles(artifact, (fileArtifact) => {
    const chunkId = fileArtifact.metadata?.chunkId ?? null;
    return chunkId !== null && !selectedChunkIds.has(chunkId);
  });
  const artifactManifest = getArtifactManifest(artifact);
  if (artifactManifest?.chunks) {
    setArtifactManifest(artifact, {
      ...artifactManifest,
      chunks: artifactManifest.chunks.filter((chunk) => selectedChunkIds.has(chunk.chunkId)),
    });
  }
  for (const chunk of artifactManifest?.chunks ?? []) {
    if (!selectedChunkIds.has(chunk.chunkId)) {
      deleteArtifactChunkManifest(artifact, chunk.chunkId);
    }
  }
}

function readBoundaryAnalysis(path) {
  const analysis = JSON.parse(readFileSync(path, "utf8"));
  if (analysis?.kind !== "js.runtime_boundary_analysis") {
    throw new Error(`Expected runtime boundary analysis at ${path}, got ${analysis?.kind ?? "unknown"}`);
  }
  return analysis;
}

function durationMsSince(startedAt) {
  return Number(process.hrtime.bigint() - startedAt) / 1_000_000;
}

function formatDuration(durationMs) {
  return `${durationMs.toFixed(3)}ms`;
}
