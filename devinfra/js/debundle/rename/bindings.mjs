import { readFileSync } from "node:fs";
import {
  renameBindingsInArtifact as renameBindingsInArtifactCore,
  renameBindingsInCode,
} from "./core.mjs";

export { renameBindingsInCode };

export function renameBindingsInArtifact(options) {
  return renameBindingsInArtifactCore({
    ...options,
    operations: loadOperations(options),
  });
}

function loadOperations(options) {
  return Array.isArray(options.operations)
    ? options.operations
    : options.operationsPath
      ? JSON.parse(readFileSync(options.operationsPath, "utf8"))
      : [];
}
