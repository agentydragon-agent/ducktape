import { readFileSync } from "node:fs";
import { expandLogicalModuleRenameOperations } from "../extract/logical_modules.mjs";
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
  const operations = Array.isArray(options.operations)
    ? options.operations
    : options.operationsPath
      ? JSON.parse(readFileSync(options.operationsPath, "utf8"))
      : [];
  return [...operations, ...expandLogicalModuleRenameOperations(operations)];
}
