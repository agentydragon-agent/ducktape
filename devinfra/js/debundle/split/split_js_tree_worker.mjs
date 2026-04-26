import { parentPort, workerData } from "node:worker_threads";
import { transformOneJsChunk } from "./split_js_tree_lib.mjs";

try {
  const result = transformOneJsChunk({
    ...workerData,
    stageName: workerData.mode === "normalize" ? "normalizeOneJsChunk" : "splitOneJsChunk",
    emitParts: workerData.mode === "split",
  });
  parentPort.postMessage({
    ok: true,
    result: {
      ...result,
      jsFiles: [...result.jsFiles.entries()],
    },
  });
} catch (error) {
  parentPort.postMessage({
    error: {
      message: error.message,
      stack: error.stack,
    },
    ok: false,
  });
}
