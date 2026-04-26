import { posix } from "node:path";
import {
  listChunkFiles,
  listChunkIds,
  requirePipelineArtifact,
  resolveArtifactImportReference,
  resolveArtifactSourceImportReference,
} from "../common/pipeline_artifact_lib.mjs";
import { transformRuntimeSources } from "../split/split_chunk_lib.mjs";

export function rewriteChunkEntrySpecifiers({ artifact }) {
  requirePipelineArtifact(artifact, "rewriteChunkEntrySpecifiers");

  let rewrittenFiles = 0;
  let rewrittenSpecifiers = 0;
  const details = [];

  for (const chunkId of listChunkIds(artifact)) {
    for (const fileArtifact of listChunkFiles(artifact, chunkId)) {
      if (!fileArtifact.ast) {
        continue;
      }
      let fileRewrites = 0;
      transformRuntimeSources(fileArtifact.ast, (source) => {
        const rewritten = rewriteChunkEntrySpecifierSource(artifact, source, {
          callerChunkId: chunkId,
          callerFile: fileArtifact.path,
        });
        if (rewritten !== source) {
          fileRewrites++;
        }
        return rewritten;
      });
      if (fileRewrites > 0) {
        rewrittenFiles++;
        rewrittenSpecifiers += fileRewrites;
        details.push({
          file: `${chunkId}/${fileArtifact.path}`,
          rewrites: fileRewrites,
        });
      }
    }
  }

  return {
    artifact,
    manifest: {
      kind: "js.rewrite_chunk_entry_specifiers_manifest",
      counts: {
        files: rewrittenFiles,
        rewrites: rewrittenSpecifiers,
      },
      details,
    },
  };
}

export function rewriteChunkEntrySpecifierSource(artifact, source, { callerChunkId, callerFile } = {}) {
  requirePipelineArtifact(artifact, "rewriteChunkEntrySpecifierSource");
  if (typeof source !== "string" || source === "") {
    return source;
  }
  if (typeof callerChunkId !== "string" || callerChunkId === "" || typeof callerFile !== "string" || callerFile === "") {
    return source;
  }
  if (!source.startsWith(".") && !source.startsWith("/")) {
    return source;
  }

  // Already-realized artifact-relative references should stay untouched.
  if (resolveArtifactImportReference(artifact, source, { callerChunkId, callerFile })) {
    return source;
  }

  const resolved = resolveArtifactSourceImportReference(artifact, source, { callerChunkId, callerFile });
  if (!resolved) {
    return source;
  }

  const callerDir = posix.join(callerChunkId, posix.dirname(callerFile));
  const targetPath = posix.join(resolved.chunkId, resolved.file);
  let rewritten = posix.relative(callerDir, targetPath);
  if (!rewritten.startsWith(".")) {
    rewritten = `./${rewritten}`;
  }
  return rewritten;
}
