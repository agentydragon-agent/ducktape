import { join } from "node:path";
import { modulePackageJson, writeJsonFile, writeTextFile } from "../common/js_module_lib.mjs";
import {
  getArtifactChunkManifest,
  getArtifactManifest,
  listArtifactChunks,
  requirePipelineArtifact,
} from "../common/pipeline_artifact_lib.mjs";
import { prepareOutputDir, relativeWorkspacePath, resolveWorkspacePath } from "../common/workspace_io_lib.mjs";
import { serializeGeneratedJsFile } from "../split/split_chunk_lib.mjs";

export function writeJsTree({ artifact, force = false, outDir }) {
  requirePipelineArtifact(artifact, "writeJsTree");
  if (typeof outDir !== "string" || outDir === "") {
    throw new Error("writeJsTree requires outDir");
  }
  const resolvedOutDir = resolveWorkspacePath(outDir);

  prepareOutputDir(resolvedOutDir, { force });

  const chunkEntries = listArtifactChunks(artifact);
  const files = [];
  for (const { chunkId, files: chunkFiles } of chunkEntries) {
    for (const file of chunkFiles) {
      const outputPath = join(resolvedOutDir, ...file.path.split("/"));
      writeTextFile(outputPath, serializeGeneratedJsFile(file));
      files.push(file.path);
    }
  }

  const snapshotManifest = getArtifactManifest(artifact);
  if (snapshotManifest) {
    writeJsonFile(join(resolvedOutDir, "manifest.json"), snapshotManifest);
  }
  for (const { chunkId } of chunkEntries) {
    const chunkManifest = getArtifactChunkManifest(artifact, chunkId);
    if (chunkManifest) {
      writeJsonFile(join(resolvedOutDir, ...chunkId.split("/"), "manifest.json"), chunkManifest);
    }
  }
  writeJsonFile(join(resolvedOutDir, "package.json"), modulePackageJson());

  return {
    artifact,
    manifest: {
      kind: "js.write_js_tree_manifest",
      outDir: relativeWorkspacePath(resolvedOutDir),
      counts: {
        chunks: chunkEntries.length,
        files: files.length,
      },
      files,
    },
  };
}
