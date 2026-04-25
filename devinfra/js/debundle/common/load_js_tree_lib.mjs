import { readFileSync } from "node:fs";
import { posix, resolve } from "node:path";
import { createEmptyPipelineArtifact, createJsArtifactFile, setJsArtifactFile } from "./pipeline_artifact_lib.mjs";
import { requireValue, resolveWorkspacePath } from "./workspace_io_lib.mjs";

export function parseLoadJsTreeArgs(argv) {
  const options = {
    help: false,
    inputRoot: undefined,
    jsListPath: undefined,
  };

  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    switch (arg) {
      case "--help":
      case "-h":
        options.help = true;
        break;
      case "--js-list":
        options.jsListPath = resolveWorkspacePath(requireValue(argv, ++index, arg));
        break;
      case "--input-root":
        options.inputRoot = resolveWorkspacePath(requireValue(argv, ++index, arg));
        break;
      default:
        throw new Error(`Unknown argument: ${arg}`);
    }
  }

  if (options.help) {
    return options;
  }
  if (!options.inputRoot) {
    throw new Error("--input-root is required");
  }
  if (!options.jsListPath) {
    throw new Error("--js-list is required");
  }
  return options;
}

export function loadJsTree({ inputRoot, jsListPath }) {
  const resolvedInputRoot = resolveWorkspacePath(inputRoot);
  const resolvedJsListPath = resolveWorkspacePath(jsListPath);
  const jsFiles = parseJsList(readFileSync(resolvedJsListPath, "utf8"));
  const artifact = createEmptyPipelineArtifact();

  for (const path of jsFiles) {
    const absolutePath = resolve(resolvedInputRoot, ...path.split("/"));
    setJsArtifactFile(
      artifact,
      createJsArtifactFile({
        path,
        content: readFileSync(absolutePath, "utf8"),
        metadata: {
          role: "source",
          sourcePath: path,
          chunkId: path.endsWith(".js") ? path.slice(0, -".js".length) : null,
        },
      })
    );
  }

  return {
    artifact,
    manifest: {
      kind: "js.loaded_js_tree",
      counts: {
        files: jsFiles.length,
      },
      jsFiles,
    },
  };
}

function parseJsList(text) {
  const paths = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "" && !line.startsWith("#"))
    .map(normalizeAssetPath);
  const unique = new Set(paths);
  if (unique.size !== paths.length) {
    throw new Error("JS list contains duplicate paths");
  }
  return paths;
}

function normalizeAssetPath(path) {
  const normalized = path.split("\\").join("/");
  if (normalized === "" || normalized.startsWith("/") || normalized.split("/").includes("..")) {
    throw new Error(`Invalid input-root-relative JS path: ${path}`);
  }
  if (!normalized.endsWith(".js")) {
    throw new Error(`Expected a .js path in JS list: ${path}`);
  }
  return posix.normalize(normalized);
}
