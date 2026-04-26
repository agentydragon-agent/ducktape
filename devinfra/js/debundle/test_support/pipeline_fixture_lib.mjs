import { computeJsAsts } from "../common/compute_js_asts_lib.mjs";
import { loadJsChunks } from "../common/load_js_chunks_lib.mjs";
import { splitJsTree } from "../split/split_js_tree_lib.mjs";

export async function buildSplitPipelineArtifactFromSnapshot({
  entryFile,
  jobs = 1,
  jsListPath,
  snapshotRoot,
}) {
  const loaded = loadJsChunks({ inputRoot: snapshotRoot, jsListPath });
  const parsed = computeJsAsts({ artifact: loaded.artifact });
  return splitJsTree({
    artifact: parsed.artifact,
    ...(entryFile ? { entryFile } : {}),
    jobs,
  });
}
