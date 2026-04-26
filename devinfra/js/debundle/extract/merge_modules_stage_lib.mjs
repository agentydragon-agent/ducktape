import { parse } from "@babel/parser";
import { DEFAULT_PARSER_OPTIONS } from "../common/js_module_lib.mjs";
import {
  createChunk,
  createFile,
  getArtifactChunkManifest,
  getArtifactManifest,
  getChunk,
  requirePipelineArtifact,
  setArtifactChunkManifest,
  setArtifactManifest,
  setChunk,
} from "../common/pipeline_artifact_lib.mjs";
import { logProgress } from "../common/workspace_io_lib.mjs";
import { extractSelectedModulePlanInAst } from "./extract_ordered_init_region_lib.mjs";
import { deriveSelectedModuleTarget } from "./selected_module_planning_lib.mjs";

export function mergeModules({ artifact, operations = [] }) {
  requirePipelineArtifact(artifact, "mergeModules");
  const mergeOperations = normalizeMergeOperations(operations);
  const artifactManifest = getArtifactManifest(artifact);

  if (mergeOperations.length === 0) {
    return {
      artifact,
      manifest: {
        kind: "js.merge_module_manifest",
        schemaVersion: 1,
        counts: {
          chunks: 0,
          mergedModules: 0,
        },
        chunks: [],
      },
    };
  }

  const operationsByChunk = new Map();
  for (const operation of mergeOperations) {
    if (!operationsByChunk.has(operation.selector.chunkId)) {
      operationsByChunk.set(operation.selector.chunkId, []);
    }
    operationsByChunk.get(operation.selector.chunkId).push(operation);
  }

  const reports = [];
  const applied = [];
  for (const [chunkId, chunkOperations] of operationsByChunk.entries()) {
    const chunk = getChunk(artifact, chunkId);
    if (!chunk) {
      throw new Error(`mergeModules missing chunk ${chunkId}`);
    }
    const state = chunk.metadata?.moduleExtractionState;
    if (!state?.originalCode || !Array.isArray(state.currentModules)) {
      throw new Error(`mergeModules requires extractAtomicModules state for chunk ${chunkId}`);
    }

    const currentModules = state.currentModules.map(cloneModulePlan);
    const resolvedTargetDir = state.targetDir ?? "modules";
    const nextModules = buildMergedModulePlans(currentModules, chunkOperations, {
      targetDir: resolvedTargetDir,
    });
    const runtimeFile = state.runtimeFile ?? chunk.entryFile;
    if (!runtimeFile) {
      throw new Error(`mergeModules missing runtimeFile for chunk ${chunkId}`);
    }
    const parserOptions = state.parserOptions ?? DEFAULT_PARSER_OPTIONS;
    const headerLines = state.headerLines ?? [];
    const loweringAst = parse(state.originalCode, parserOptions);
    const result = extractSelectedModulePlanInAst(
      loweringAst,
      {
        kind: "js.selected_module_plan",
        modulePlans: nextModules,
      },
      {
        chunkId,
        file: runtimeFile,
        headerLines,
        idPrefix: "merged_module",
        targetDir: resolvedTargetDir,
      }
    );
    const moduleByTargetFile = new Map(nextModules.map((modulePlan) => [modulePlan.targetFile, modulePlan]));

    const nextChunk = createChunk({
      chunkId,
      entryFile: runtimeFile,
      files: [...result.jsFiles.entries()].map(([relativePath, fileArtifact]) => {
        const modulePlan = moduleByTargetFile.get(relativePath) ?? null;
        return createFile({
          path: relativePath,
          ast: fileArtifact.ast,
          headerLines: fileArtifact.headerLines,
          metadata: {
            ...(chunk.files.get(runtimeFile)?.metadata ?? {}),
            chunkFile: relativePath,
            chunkId,
            role: relativePath === runtimeFile ? "entry" : "module",
            ...(modulePlan
              ? {
                  moduleExtraction: {
                    id: modulePlan.id,
                    kind: "module",
                    nameHint: modulePlan.nameHint,
                    ownerIds: [...modulePlan.ownerIds],
                    unitIds: [...modulePlan.unitIds],
                  },
                }
              : {}),
          },
          parserOptions,
        });
      }),
      metadata: {
        ...chunk.metadata,
        moduleExtractionState: {
          ...state,
          currentModules: nextModules.map(cloneModulePlan),
          mode: "merged",
        },
      },
    });
    setChunk(artifact, nextChunk);

    const chunkManifest = getArtifactChunkManifest(artifact, chunkId);
    setArtifactChunkManifest(artifact, chunkId, {
      ...chunkManifest,
      entryFile: runtimeFile,
      mergeModules: {
        count: chunkOperations.length,
        mergedModuleIds: nextModules.map((modulePlan) => modulePlan.id),
      },
      orderedInitExtractions: result.applied,
    });
    applied.push(...result.applied);
    reports.push({
      chunkId,
      mergedModuleIds: nextModules.map((modulePlan) => modulePlan.id),
      operationIds: chunkOperations.map((operation) => operation.id),
    });
  }

  setArtifactManifest(artifact, {
    ...artifactManifest,
    counts: {
      ...(artifactManifest?.counts ?? {}),
      orderedInitExtractions: applied.length,
    },
    mergeModules: {
      chunkCount: reports.length,
      mergedModuleCount: reports.reduce((sum, report) => sum + report.mergedModuleIds.length, 0),
    },
    orderedInitExtractions: applied,
  });

  logProgress(`merge-modules done chunks=${reports.length}`);
  return {
    artifact,
    manifest: {
      kind: "js.merge_module_manifest",
      schemaVersion: 1,
      counts: {
        chunks: reports.length,
        mergedModules: reports.reduce((sum, report) => sum + report.mergedModuleIds.length, 0),
      },
      chunks: reports,
    },
  };
}

function normalizeMergeOperations(operations) {
  return operations.filter((operation) => operation?.operation === "merge_module").map((operation) => {
    if (typeof operation?.id !== "string" || operation.id === "") {
      throw new Error("merge_module operation requires id");
    }
    if (typeof operation?.selector?.chunkId !== "string" || operation.selector.chunkId === "") {
      throw new Error(`merge_module ${operation.id} requires selector.chunkId`);
    }
    if (!Array.isArray(operation?.selector?.moduleIds) || operation.selector.moduleIds.length === 0) {
      throw new Error(`merge_module ${operation.id} requires selector.moduleIds`);
    }
    return {
      ...operation,
      selector: {
        chunkId: normalizeRelativeFile(operation.selector.chunkId),
        moduleIds: [...new Set(operation.selector.moduleIds)],
      },
      target: operation.target ?? {},
    };
  });
}

function buildMergedModulePlans(currentModules, operations, { targetDir }) {
  const moduleById = new Map(currentModules.map((modulePlan) => [modulePlan.id, modulePlan]));
  const operationByModuleId = new Map();
  for (const operation of operations) {
    for (const moduleId of operation.selector.moduleIds) {
      if (!moduleById.has(moduleId)) {
        throw new Error(`merge_module ${operation.id} references unknown module ${moduleId}`);
      }
      if (operationByModuleId.has(moduleId)) {
        throw new Error(`merge_module operations overlap on module ${moduleId}`);
      }
      operationByModuleId.set(moduleId, operation);
    }
  }

  const emittedOperations = new Set();
  const nextModules = [];
  for (const currentModule of currentModules) {
    const operation = operationByModuleId.get(currentModule.id);
    if (!operation) {
      nextModules.push(cloneModulePlan(currentModule));
      continue;
    }
    if (emittedOperations.has(operation.id)) {
      continue;
    }
    emittedOperations.add(operation.id);
    const selectedModules = operation.selector.moduleIds
      .map((moduleId) => moduleById.get(moduleId))
      .sort((left, right) => left.startOrdinal - right.startOrdinal || left.id.localeCompare(right.id));
    nextModules.push(mergeModuleGroup(selectedModules, operation, nextModules.length, { targetDir }));
  }
  return nextModules.sort((left, right) => left.startOrdinal - right.startOrdinal || left.id.localeCompare(right.id));
}

function mergeModuleGroup(selectedModules, operation, index, { targetDir }) {
  const targetBasename =
    typeof operation.target?.basename === "string" && operation.target.basename !== ""
      ? sanitizeIdentifier(operation.target.basename)
      : sanitizeIdentifier(operation.id);
  const baseModule = {
    attachedItemIds: [...new Set(selectedModules.flatMap((modulePlan) => modulePlan.attachedItemIds))].sort(),
    basename: targetBasename,
    bytes: selectedModules.some((modulePlan) => modulePlan.bytes === null)
      ? null
      : selectedModules.reduce((sum, modulePlan) => sum + modulePlan.bytes, 0),
    id: operation.id,
    index,
    lines: selectedModules.reduce((sum, modulePlan) => sum + modulePlan.lines, 0),
    memberNames: [...new Set(selectedModules.flatMap((modulePlan) => modulePlan.memberNames))].sort(),
    nameHint: targetBasename,
    ownerIds: dedupeIds(selectedModules.flatMap((modulePlan) => modulePlan.ownerIds)),
    startOrdinal: Math.min(...selectedModules.map((modulePlan) => modulePlan.startOrdinal)),
    unitIds: dedupeIds(selectedModules.flatMap((modulePlan) => modulePlan.unitIds)),
  };
  const derivedTarget = deriveSelectedModuleTarget(baseModule, index, { targetDir });
  return {
    ...baseModule,
    initName:
      typeof operation.target?.init === "string" && operation.target.init !== ""
        ? operation.target.init
        : derivedTarget.init,
    targetFile:
      typeof operation.target?.file === "string" && operation.target.file !== ""
        ? normalizeRelativeFile(operation.target.file)
        : derivedTarget.file,
  };
}

function cloneModulePlan(modulePlan) {
  return {
    attachedItemIds: [...modulePlan.attachedItemIds],
    basename: modulePlan.basename,
    ...(modulePlan.bytes === null ? { bytes: null } : { bytes: modulePlan.bytes }),
    id: modulePlan.id,
    index: modulePlan.index,
    ...(modulePlan.initName ? { initName: modulePlan.initName } : {}),
    lines: modulePlan.lines,
    memberNames: [...modulePlan.memberNames],
    nameHint: modulePlan.nameHint,
    ownerIds: [...modulePlan.ownerIds],
    startOrdinal: modulePlan.startOrdinal,
    ...(modulePlan.targetFile ? { targetFile: modulePlan.targetFile } : {}),
    unitIds: [...modulePlan.unitIds],
  };
}

function dedupeIds(values) {
  return [...new Set(values)];
}

function normalizeRelativeFile(value) {
  if (typeof value !== "string" || value === "") {
    throw new Error(`Expected a non-empty relative path, got: ${value}`);
  }
  const normalized = value.replace(/^\.\/+/, "").replace(/\\/g, "/");
  if (normalized === "." || normalized.startsWith("/") || normalized.split("/").includes("..")) {
    throw new Error(`Invalid relative path: ${value}`);
  }
  return normalized;
}

function sanitizeIdentifier(value) {
  return value
    .replace(/[^A-Za-z0-9_$]+/g, "_")
    .replace(/^[^A-Za-z_$]+/, "_")
    .replace(/_+/g, "_");
}
