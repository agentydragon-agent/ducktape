import { posix } from "node:path";
import { cloneDefaultParserOptions } from "./js_module_lib.mjs";

const FILE_INDEX_CACHE = new WeakMap();
const CHUNK_INDEX_CACHE = new WeakMap();

export function createPipelineArtifact({ files = [], extras = {} } = {}) {
  const artifact = {
    kind: "js.pipeline_artifact",
    tree: {
      files: files.map(normalizeJsArtifactFile),
    },
    extras: normalizeArtifactExtras(extras),
  };
  primeArtifactIndexes(artifact);
  return artifact;
}

export function createEmptyPipelineArtifact() {
  return createPipelineArtifact();
}

export function isPipelineArtifact(value) {
  return value?.kind === "js.pipeline_artifact" && Array.isArray(value?.tree?.files);
}

export function requirePipelineArtifact(artifact, stageName) {
  if (!isPipelineArtifact(artifact)) {
    throw new Error(`${stageName} requires a js.pipeline_artifact`);
  }
  return artifact;
}

export function createJsArtifactFile({
  path,
  content = undefined,
  ast = undefined,
  parserOptions = undefined,
  headerLines = undefined,
  metadata = undefined,
} = {}) {
  if (typeof path !== "string" || path === "") {
    throw new Error(`Expected a non-empty JS artifact path, got: ${path}`);
  }
  return normalizeJsArtifactFile({
    path,
    language: "js",
    ...(content !== undefined ? { content } : {}),
    ...(ast !== undefined ? { ast } : {}),
    ...(parserOptions !== undefined ? { parserOptions } : {}),
    ...(headerLines !== undefined ? { headerLines } : {}),
    ...(metadata !== undefined ? { metadata } : {}),
  });
}

export function listJsArtifactFiles(artifact) {
  return requirePipelineArtifact(artifact, "listJsArtifactFiles").tree.files;
}

export function getJsArtifactFile(artifact, path) {
  const index = fileIndex(artifact);
  return index.get(path) ?? null;
}

export function requireJsArtifactFile(artifact, path, stageName = "stage") {
  const file = getJsArtifactFile(artifact, path);
  if (!file) {
    throw new Error(`${stageName} missing JS artifact file: ${path}`);
  }
  return file;
}

export function setJsArtifactFile(artifact, file) {
  requirePipelineArtifact(artifact, "setJsArtifactFile");
  const normalized = normalizeJsArtifactFile(file);
  const index = fileIndex(artifact);
  const existing = index.get(normalized.path);
  if (existing) {
    const files = artifact.tree.files;
    const position = files.indexOf(existing);
    files[position] = normalized;
  } else {
    artifact.tree.files.push(normalized);
  }
  index.set(normalized.path, normalized);
  updateChunkIndexForSet(artifact, existing, normalized);
  return artifact;
}

export function deleteJsArtifactFile(artifact, path) {
  requirePipelineArtifact(artifact, "deleteJsArtifactFile");
  const index = fileIndex(artifact);
  const existing = index.get(path);
  if (!existing) {
    return false;
  }
  const position = artifact.tree.files.indexOf(existing);
  if (position >= 0) {
    artifact.tree.files.splice(position, 1);
  }
  index.delete(path);
  removeChunkFileFromIndex(artifact, existing);
  return true;
}

export function replaceJsArtifactFiles(artifact, files) {
  requirePipelineArtifact(artifact, "replaceJsArtifactFiles");
  artifact.tree.files = files.map(normalizeJsArtifactFile);
  clearArtifactIndexes(artifact);
  primeArtifactIndexes(artifact);
  return artifact;
}

export function removeJsArtifactFiles(artifact, predicate) {
  requirePipelineArtifact(artifact, "removeJsArtifactFiles");
  artifact.tree.files = artifact.tree.files.filter((file) => !predicate(file));
  clearArtifactIndexes(artifact);
  primeArtifactIndexes(artifact);
  return artifact;
}

export function listArtifactChunkIds(artifact) {
  return [...chunkIndex(artifact).keys()].sort();
}

export function listArtifactChunks(artifact) {
  const index = chunkIndex(artifact);
  return [...index.keys()].sort().map((chunkId) => ({
    chunkId,
    files: [...index.get(chunkId)],
  }));
}

export function listChunkJsArtifactFiles(artifact, chunkId) {
  return [...(chunkIndex(artifact).get(chunkId) ?? [])];
}

export function listChunkJsArtifactRelativeFiles(artifact, chunkId) {
  const files = listChunkJsArtifactFiles(artifact, chunkId).map((file) => relativeChunkFile(chunkId, file.path));
  files.sort();
  const entryFile = getChunkEntryRelativeFile(artifact, chunkId);
  if (entryFile) {
    return sortFilesWithEntryFirst(files, entryFile);
  }
  return files;
}

export function getChunkEntryRelativeFile(artifact, chunkId) {
  const manifest = getArtifactChunkManifest(artifact, chunkId);
  const chunkFiles = listChunkJsArtifactFiles(artifact, chunkId);
  const relativeFiles = chunkFiles.map((file) => relativeChunkFile(chunkId, file.path));

  if (relativeFiles.length === 0) {
    return null;
  }

  if (manifest?.entryFile && relativeFiles.includes(manifest.entryFile)) {
    return manifest.entryFile;
  }

  const roleEntry = chunkFiles.find(
    (file) => file.metadata?.role === "entry" || file.metadata?.role === "runtime"
  );
  if (roleEntry) {
    return relativeChunkFile(chunkId, roleEntry.path);
  }

  return [...relativeFiles].sort()[0];
}

export function getChunkEntryArtifactFile(artifact, chunkId) {
  const entryFile = getChunkEntryRelativeFile(artifact, chunkId);
  if (!entryFile) {
    return null;
  }
  return getJsArtifactFile(artifact, `${chunkId}/${entryFile}`);
}

export function resolveArtifactImportReference(artifact, source, { callerChunkId, callerFile } = {}) {
  requirePipelineArtifact(artifact, "resolveArtifactImportReference");
  if (typeof source !== "string" || source === "" || typeof callerChunkId !== "string" || typeof callerFile !== "string") {
    return null;
  }
  if (!source.startsWith(".")) {
    return null;
  }
  const callerDir = posix.join(callerChunkId, posix.dirname(callerFile));
  const resolvedPath = posix.normalize(posix.join(callerDir, source));
  const targetFile = getJsArtifactFile(artifact, resolvedPath);
  if (!targetFile) {
    return null;
  }
  const targetChunkId = artifactChunkIdForFile(targetFile);
  if (!targetChunkId) {
    return null;
  }
  return {
    chunkId: targetChunkId,
    file: relativeChunkFile(targetChunkId, targetFile.path),
    path: resolvedPath,
  };
}

export function artifactChunkIdForFile(file) {
  return file.metadata?.chunkId ?? null;
}

export function ensureArtifactExtras(artifact) {
  requirePipelineArtifact(artifact, "ensureArtifactExtras");
  if (!artifact.extras) {
    artifact.extras = normalizeArtifactExtras({});
  }
  if (!artifact.extras.manifests) {
    artifact.extras.manifests = { root: null, chunks: new Map() };
  } else if (!(artifact.extras.manifests.chunks instanceof Map)) {
    artifact.extras.manifests.chunks = new Map(artifact.extras.manifests.chunks ?? []);
  }
  if (!artifact.extras.annotations) {
    artifact.extras.annotations = {};
  }
  return artifact.extras;
}

export function getArtifactManifest(artifact) {
  return ensureArtifactExtras(artifact).manifests.root ?? null;
}

export function getArtifactManifestChunks(artifact) {
  const manifest = getArtifactManifest(artifact);
  if (Array.isArray(manifest?.chunks)) {
    return manifest.chunks;
  }
  return listArtifactChunkIds(artifact).map((chunkId) => ({ chunkId }));
}

export function getArtifactManifestOrDerived(artifact) {
  const manifest = getArtifactManifest(artifact);
  if (manifest) {
    return manifest;
  }
  return {
    schemaVersion: 1,
    counts: {
      chunks: listArtifactChunkIds(artifact).length,
    },
    chunks: getArtifactManifestChunks(artifact),
  };
}

export function setArtifactManifest(artifact, manifest) {
  ensureArtifactExtras(artifact).manifests.root = manifest;
  return artifact;
}

export function getArtifactChunkManifest(artifact, chunkId) {
  return ensureArtifactExtras(artifact).manifests.chunks.get(chunkId) ?? null;
}

export function getArtifactChunkManifestOrDerived(artifact, chunkId) {
  const manifest = getArtifactChunkManifest(artifact, chunkId);
  const files = listChunkJsArtifactFiles(artifact, chunkId);
  if (files.length === 0) {
    return manifest ?? null;
  }

  const relativeFiles = files.map((file) => relativeChunkFile(chunkId, file.path)).sort();
  const entryFile = getChunkEntryRelativeFile(artifact, chunkId);
  const parser =
    manifest?.parser ??
    files.find((file) => file.path === `${chunkId}/${entryFile}`)?.parserOptions ??
    files[0]?.parserOptions ??
    cloneDefaultParserOptions();
  const fileRecords = sortFilesWithEntryFirst(relativeFiles, entryFile).map((file) => ({
    file,
    role: file === entryFile ? "entry" : "module",
  }));

  return {
    schemaVersion: 1,
    chunkId,
    parser,
    ...(manifest ?? {}),
    entryFile,
    files: manifest?.files ?? fileRecords,
    parts: manifest?.parts ?? fileRecords.filter((file) => file.file !== entryFile).map((file) => ({ file: file.file })),
  };
}

export function setArtifactChunkManifest(artifact, chunkId, manifest) {
  ensureArtifactExtras(artifact).manifests.chunks.set(chunkId, manifest);
  return artifact;
}

export function deleteArtifactChunkManifest(artifact, chunkId) {
  return ensureArtifactExtras(artifact).manifests.chunks.delete(chunkId);
}

export function listArtifactChunkManifests(artifact) {
  return ensureArtifactExtras(artifact).manifests.chunks;
}

export function getArtifactVendorAnnotations(artifact) {
  const extras = ensureArtifactExtras(artifact);
  if (!(extras.annotations.vendor instanceof Map)) {
    extras.annotations.vendor = new Map(extras.annotations.vendor ?? []);
  }
  return extras.annotations.vendor;
}

export function setArtifactVendorAnnotations(artifact, annotations) {
  ensureArtifactExtras(artifact).annotations.vendor = annotations;
  return artifact;
}

function normalizeJsArtifactFile(file) {
  if (file?.language && file.language !== "js") {
    throw new Error(`Pipeline artifact only supports js files, got: ${file.language}`);
  }
  return {
    path: file.path,
    language: "js",
    ...(file.content !== undefined ? { content: file.content } : {}),
    ...(file.ast !== undefined ? { ast: file.ast } : {}),
    ...(file.parserOptions !== undefined ? { parserOptions: file.parserOptions } : {}),
    ...(file.headerLines !== undefined ? { headerLines: [...file.headerLines] } : {}),
    metadata: { ...(file.metadata ?? {}) },
  };
}


function normalizeArtifactExtras(extras) {
  const manifests = extras.manifests
    ? {
        root: extras.manifests.root ?? extras.manifests.snapshot ?? null,
        chunks: extras.manifests.chunks instanceof Map ? extras.manifests.chunks : new Map(extras.manifests.chunks ?? []),
      }
    : {
        root: null,
        chunks: new Map(),
      };
  const annotations = { ...(extras.annotations ?? {}) };
  if (annotations.vendor && !(annotations.vendor instanceof Map)) {
    annotations.vendor = new Map(annotations.vendor);
  }
  return {
    ...extras,
    manifests,
    annotations,
  };
}

function fileIndex(artifact) {
  requirePipelineArtifact(artifact, "fileIndex");
  return FILE_INDEX_CACHE.get(artifact) ?? primeArtifactIndexes(artifact).fileIndex;
}

function chunkIndex(artifact) {
  requirePipelineArtifact(artifact, "chunkIndex");
  return CHUNK_INDEX_CACHE.get(artifact) ?? primeArtifactIndexes(artifact).chunkIndex;
}

function primeArtifactIndexes(artifact) {
  const fileIndex = new Map();
  const chunkIndex = new Map();
  for (const file of artifact.tree.files) {
    fileIndex.set(file.path, file);
    const chunkId = artifactChunkIdForFile(file);
    if (!chunkId) {
      continue;
    }
    if (!chunkIndex.has(chunkId)) {
      chunkIndex.set(chunkId, []);
    }
    chunkIndex.get(chunkId).push(file);
  }
  FILE_INDEX_CACHE.set(artifact, fileIndex);
  CHUNK_INDEX_CACHE.set(artifact, chunkIndex);
  return { fileIndex, chunkIndex };
}

function clearArtifactIndexes(artifact) {
  FILE_INDEX_CACHE.delete(artifact);
  CHUNK_INDEX_CACHE.delete(artifact);
}

function updateChunkIndexForSet(artifact, existing, normalized) {
  const index = chunkIndex(artifact);
  const existingChunkId = existing ? artifactChunkIdForFile(existing) : null;
  const normalizedChunkId = artifactChunkIdForFile(normalized);

  if (existingChunkId === normalizedChunkId && existingChunkId) {
    const files = index.get(existingChunkId) ?? [];
    const position = files.indexOf(existing);
    if (position >= 0) {
      files[position] = normalized;
      return;
    }
  } else if (existing) {
    removeChunkFileFromIndex(artifact, existing);
  }

  if (!normalizedChunkId) {
    return;
  }
  if (!index.has(normalizedChunkId)) {
    index.set(normalizedChunkId, []);
  }
  index.get(normalizedChunkId).push(normalized);
}

function removeChunkFileFromIndex(artifact, file) {
  const chunkId = artifactChunkIdForFile(file);
  if (!chunkId) {
    return;
  }
  const index = chunkIndex(artifact);
  const files = index.get(chunkId);
  if (!files) {
    return;
  }
  const position = files.indexOf(file);
  if (position >= 0) {
    files.splice(position, 1);
  }
  if (files.length === 0) {
    index.delete(chunkId);
  }
}

function relativeChunkFile(chunkId, filePath) {
  return filePath.slice(`${chunkId}/`.length);
}

function sortFilesWithEntryFirst(files, entryFile) {
  const sorted = [...files].sort();
  if (!entryFile) {
    return sorted;
  }
  const index = sorted.indexOf(entryFile);
  if (index <= 0) {
    return sorted;
  }
  sorted.splice(index, 1);
  sorted.unshift(entryFile);
  return sorted;
}
