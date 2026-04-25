import { parentPort, workerData } from "node:worker_threads";
import { splitOneJsChunk } from "./split_js_tree_lib.mjs";

try {
  const result = splitOneJsChunk(workerData);
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
