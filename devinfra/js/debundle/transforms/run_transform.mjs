#!/usr/bin/env node

import { requireValue } from "../common/workspace_io_lib.mjs";
import { runTransformSpec } from "./run_transform_lib.mjs";

async function main() {
  const specPath = parseArgs(process.argv.slice(2));
  const result = await runTransformSpec(specPath);
  process.stdout.write(`Ran ${result.steps.length} transform steps from ${result.specPath}\n`);
  for (const step of result.steps) {
    process.stdout.write(`- ${step.id}: ${step.operation}\n`);
  }
}

function parseArgs(argv) {
  let specPath = null;
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (arg === "--spec") {
      specPath = requireValue(argv, ++index, arg);
    } else if (arg === "--help" || arg === "-h") {
      process.stdout.write(`Usage:
  run_transform --spec <spec.jsonc>

Runs the JavaScript transform pipeline described by the spec. Pipeline stages
dispatch directly to registered functions; this target does not invoke Bazel
from inside the pipeline. Specs are parsed as JSON with comments.
`);
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  if (specPath === null) {
    throw new Error("--spec is required");
  }
  return specPath;
}

await main();
