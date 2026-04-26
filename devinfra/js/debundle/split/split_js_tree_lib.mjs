import { availableParallelism } from "node:os";
import { posix } from "node:path";
import { Worker } from "node:worker_threads";
import {
  createEmptyArtifact,
  createFile,
  listChunks,
  requirePipelineArtifact,
  replaceChunks,
  setArtifactChunkManifest,
  setArtifactManifest,
} from "../common/pipeline_artifact_lib.mjs";
import { formatDuration, logProgress } from "../common/workspace_io_lib.mjs";
import { DEFAULT_SPLIT_ENTRY_FILE, normalizeChunkEntryFile, splitScopeHoistedChunkAst } from "./split_chunk_lib.mjs";

// TODO: Re-enable part emission once the replacement splitter can justify the
// added tree size and downstream memory cost. The current part explosion is
// disabled by default because it bloats the live pipeline without paying for
// itself in coverage.
export async function splitJsTree({ artifact, jobs, emitParts = false, entryFile = DEFAULT_SPLIT_ENTRY_FILE }) {
  requirePipelineArtifact(artifact, "splitJsTree");
  const normalizedEntryFile = normalizeChunkEntryFile(entryFile);
  const sourceChunks = listChunks(artifact);
  const effectiveJobs = jobs ?? defaultJobs();
  const jsPaths = sourceChunks.map(sourcePathForLoadedChunk);

  logProgress(`split start files=${sourceChunks.length} jobs=${effectiveJobs} mode=pipeline`);
  const startedAt = process.hrtime.bigint();

  const chunks =
    effectiveJobs === 1 || sourceChunks.length <= 1
      ? sourceChunks.map((chunk) =>
          splitOneJsChunk({ artifactChunk: chunk, emitParts, entryFile: normalizedEntryFile, jsPaths })
        )
      : await splitChunksParallel({
          artifactChunks: sourceChunks,
          emitParts,
          entryFile: normalizedEntryFile,
          jobs: effectiveJobs,
          jsPaths,
        });

  const nextArtifact = createEmptyArtifact();
  const manifest = buildJsTreeManifest(chunks);

  const outputChunks = [];
  for (const chunk of chunks) {
    setArtifactChunkManifest(nextArtifact, chunk.chunkId, chunk.manifest);
    outputChunks.push({
      chunkId: chunk.chunkId,
      entryFile: chunk.manifest.entryFile,
      files: [...chunk.jsFiles.entries()].map(([relativeFile, fileArtifact]) =>
        createFile({
          path: relativeFile,
          ast: fileArtifact.ast,
          headerLines: fileArtifact.headerLines,
          parserOptions: chunk.manifest.parser,
          metadata: {
            chunkFile: relativeFile,
            chunkId: chunk.chunkId,
            role: relativeFile === chunk.manifest.entryFile ? "entry" : "module",
            sourcePath: chunk.inputPath,
          },
        })
      ),
      metadata: {
        sourcePath: chunk.inputPath,
      },
    });
  }
  replaceChunks(nextArtifact, outputChunks);
  setArtifactManifest(nextArtifact, manifest);

  const durationMs = Number(process.hrtime.bigint() - startedAt) / 1_000_000;
  logProgress(
    `split done chunks=${manifest.counts.chunks} parts=${manifest.counts.parts} duration=${formatDuration(
      durationMs
    )} maxChunk=${formatDuration(Math.max(...chunks.map((chunk) => chunk.timing.durationMs)))} sumChunks=${formatDuration(
      chunks.reduce((sum, chunk) => sum + chunk.timing.durationMs, 0)
    )}`
  );
  for (const chunk of slowestChunks(chunks, 8)) {
    logProgress(
      `split slow-chunk chunk=${chunk.chunkId} duration=${formatDuration(chunk.timing.durationMs)} input=${formatBytes(
        chunk.timing.inputBytes
      )} parts=${chunk.counts.parts} keptOwners=${chunk.counts.keptTopLevelDeclarationOwners}`
    );
  }

  return {
    artifact: nextArtifact,
    manifest,
  };
}

export function splitOneJsChunk({ artifactChunk, emitParts = false, entryFile = DEFAULT_SPLIT_ENTRY_FILE, jsPaths }) {
  const entryArtifactFile = artifactChunk?.files?.find((file) => file.path === artifactChunk.entryFile);
  if (!entryArtifactFile?.ast) {
    throw new Error(
      `splitOneJsChunk requires AST for file: ${artifactChunk?.chunkId ?? "<unknown>"}/${artifactChunk?.entryFile ?? "<entry>"}`
    );
  }
  const normalizedEntryFile = normalizeChunkEntryFile(entryFile);
  const startedAt = process.hrtime.bigint();
  const jsFileSet = new Set(jsPaths);
  const jsPath = sourcePathForLoadedChunk(artifactChunk);
  const chunkId = artifactChunk.chunkId;
  const inputBytes = entryArtifactFile.content ? Buffer.byteLength(entryArtifactFile.content) : 0;
  const result = splitScopeHoistedChunkAst(entryArtifactFile.ast, {
    chunkId,
    entryFile: normalizedEntryFile,
    emitParts,
    includeJsFileAsts: true,
    rewriteEntryImportSource: (source) => rewriteEntryImportSource(source, jsPath, jsFileSet, normalizedEntryFile),
    sourcePath: jsPath,
  });
  return {
    chunkId,
    inputPath: jsPath,
    counts: result.manifest.counts,
    jsFiles: result.jsFiles,
    manifest: result.manifest,
    timing: {
      durationMs: Number(process.hrtime.bigint() - startedAt) / 1_000_000,
      inputBytes,
    },
  };
}

function splitChunksParallel({ artifactChunks, emitParts, entryFile, jobs, jsPaths }) {
  const results = new Array(artifactChunks.length);
  let nextIndex = 0;
  let active = 0;
  let firstError;

  return waitForAll();

  function waitForAll() {
    return new Promise((resolvePromise, rejectPromise) => {
      const startNext = () => {
        if (firstError) {
          rejectPromise(firstError);
          return;
        }
        if (nextIndex >= artifactChunks.length && active === 0) {
          resolvePromise(results);
          return;
        }
        while (active < jobs && nextIndex < artifactChunks.length) {
          const index = nextIndex++;
          active++;
          runWorker({ artifactChunk: artifactChunks[index], emitParts, entryFile, jsPaths })
            .then((result) => {
              results[index] = {
                ...result,
                jsFiles: new Map(result.jsFiles),
              };
            })
            .catch((error) => {
              firstError = error;
            })
            .finally(() => {
              active--;
              startNext();
            });
        }
      };
      startNext();
    });
  }
}

function runWorker(workerData) {
  return new Promise((resolvePromise, rejectPromise) => {
    const worker = new Worker(new URL("./split_js_tree_worker.mjs", import.meta.url), { workerData });
    worker.once("message", (message) => {
      if (message.ok) {
        resolvePromise(message.result);
      } else {
        const error = new Error(message.error?.message ?? "worker failed");
        error.stack = message.error?.stack;
        rejectPromise(error);
      }
    });
    worker.once("error", rejectPromise);
    worker.once("exit", (code) => {
      if (code !== 0) {
        rejectPromise(new Error(`split worker exited with code ${code}`));
      }
    });
  });
}

function buildJsTreeManifest(chunks) {
  return {
    schemaVersion: 1,
    counts: {
      chunks: chunks.length,
      parts: chunks.reduce((count, chunk) => count + chunk.counts.parts, 0),
      splitFunctionDeclarations: chunks.reduce((count, chunk) => count + chunk.counts.splitFunctionDeclarations, 0),
      keptTopLevelDeclarationOwners: chunks.reduce(
        (count, chunk) => count + chunk.counts.keptTopLevelDeclarationOwners,
        0
      ),
      topLevelSideEffects: chunks.reduce((count, chunk) => count + chunk.counts.topLevelSideEffects, 0),
      exportAliases: chunks.reduce((count, chunk) => count + chunk.counts.exportAliases, 0),
      unresolvedExports: chunks.reduce((count, chunk) => count + chunk.counts.unresolvedExports, 0),
    },
    chunks: chunks.map((chunk) => ({
      chunkId: chunk.chunkId,
      sourcePath: chunk.inputPath,
    })),
  };
}

function formatBytes(bytes) {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(1)}MiB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)}KiB`;
  }
  return `${bytes}B`;
}

function defaultJobs() {
  return Math.max(1, Math.min(availableParallelism() - 1, 8));
}

function slowestChunks(chunks, limit) {
  return [...chunks].sort((left, right) => right.timing.durationMs - left.timing.durationMs).slice(0, limit);
}

export function normalizeAssetPath(path) {
  const normalized = path.split("\\").join("/");
  if (normalized === "" || normalized.startsWith("/") || normalized.split("/").includes("..")) {
    throw new Error(`Invalid snapshot-relative JS path: ${path}`);
  }
  if (!normalized.endsWith(".js")) {
    throw new Error(`Expected a .js path in JS list: ${path}`);
  }
  return posix.normalize(normalized);
}

export function chunkIdForJsPath(jsPath) {
  return jsPath.slice(0, -".js".length);
}

function sourcePathForLoadedChunk(chunk) {
  return normalizeAssetPath(chunk.metadata?.sourcePath ?? `${chunk.chunkId}.js`);
}

function rewriteEntryImportSource(source, importerJsPath, jsFileSet, entryFile) {
  if (!source.startsWith(".") && !source.startsWith("/")) {
    return source;
  }

  const importedJsPath = source.startsWith("/")
    ? posix.normalize(source.slice(1))
    : posix.normalize(posix.join(posix.dirname(importerJsPath), source));
  if (!jsFileSet.has(importedJsPath)) {
    return source;
  }

  const entryDir = posix.dirname(entryFile);
  const importerOutDir =
    entryDir === "." ? chunkIdForJsPath(importerJsPath) : posix.join(chunkIdForJsPath(importerJsPath), entryDir);
  const importedEntry = posix.join(chunkIdForJsPath(importedJsPath), entryFile);
  let rewritten = posix.relative(importerOutDir, importedEntry);
  if (!rewritten.startsWith(".")) {
    rewritten = `./${rewritten}`;
  }
  return rewritten;
}
