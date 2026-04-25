import { computeJsAsts } from "../common/compute_js_asts_lib.mjs";
import { loadJsTree } from "../common/load_js_tree_lib.mjs";
import { splitJsTree } from "../split/split_js_tree_lib.mjs";

export async function buildSplitPipelineArtifactFromSnapshot({
  entryFile,
  jobs = 1,
  jsListPath,
  snapshotRoot,
}) {
  const loaded = loadJsTree({ inputRoot: snapshotRoot, jsListPath });
  const parsed = computeJsAsts({ artifact: loaded.artifact });
  return splitJsTree({
    artifact: parsed.artifact,
    ...(entryFile ? { entryFile } : {}),
    jobs,
  });
}
