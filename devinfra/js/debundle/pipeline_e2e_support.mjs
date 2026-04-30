import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { createWebFixtureRoots, runNodeScript, writeSnapshotFixture } from "./test_support/fixtures.mjs";

let moduleExportAssertionCounter = 0;
let generatedModuleScriptCounter = 0;

export async function runLogicalModulesE2eFixture({ chunkId = "static/app", operations, prefix, source }) {
  const { extractedRoot, outRoot, snapshotRoot } = createWebFixtureRoots(prefix);
  const entryFile = `${chunkId}.js`;
  writeSnapshotFixture({
    extractedRoot,
    files: {
      [entryFile]: source,
    },
    jsFiles: [entryFile],
    snapshotRoot,
  });

  mkdirSync(outRoot, { recursive: true });
  const specPath = join(outRoot, "transform_spec.jsonc");
  writeJsonFile(specPath, {
    kind: "js.ast_transform_spec",
    operations: [
      ...operations,
      {
        id: "logical__residual_unhandled",
        operation: "define_residual_module",
        selector: {
          chunkId,
        },
        target: {
          path: "residual/unhandled",
        },
      },
    ],
    pipeline: [
      {
        id: "load",
        operation: "load_js_chunks",
        args: {
          inputRoot: snapshotRoot,
          jsListPath: join(extractedRoot, "js-files.txt"),
        },
      },
      {
        id: "parse",
        operation: "compute_js_asts",
      },
      {
        id: "normalize",
        operation: "normalize_js_chunks",
        args: {
          jobs: 1,
        },
      },
      {
        id: "logical",
        operation: "materialize_logical_modules",
        args: {
          chunkIds: [chunkId],
          pruneOtherChunks: false,
        },
      },
      {
        id: "write",
        operation: "write_js_tree",
        args: {
          force: true,
          outDir: outRoot,
        },
      },
    ],
  });
  runTransformCli(specPath);

  return {
    chunkId,
    entryPath: join(outRoot, ...chunkId.split("/"), "entry.js"),
    outRoot,
    snapshotRoot,
  };
}

function runTransformCli(specPath) {
  const runTransformBin = process.env.DUCKTAPE_RUN_TRANSFORM_BIN;
  assert.ok(
    runTransformBin,
    "DUCKTAPE_RUN_TRANSFORM_BIN must point at //devinfra/js/debundle/transforms:run_transform"
  );
  const result = spawnSync(runTransformBin, ["--spec", specPath], {
    encoding: "utf8",
  });
  assert.equal(result.signal, null);
  assert.equal(result.status, 0, result.stderr || result.stdout);
}

export function assertEntryOutput(fixture, expectedStdout) {
  assertNodeOutput(fixture.entryPath, {
    expectedStdout,
  });
}

export function assertModuleExports({ excludes = [], includes = [], modulePath, outRoot }) {
  const assertionPath = join(outRoot, `assert_module_exports_${moduleExportAssertionCounter++}.mjs`);
  writeFileSync(
    assertionPath,
    `const mod = await import(${JSON.stringify(`./${modulePath}`)});
const includes = ${JSON.stringify(includes)};
const excludes = ${JSON.stringify(excludes)};
for (const name of includes) {
  if (!Object.prototype.hasOwnProperty.call(mod, name)) {
    throw new Error(\`Expected \${name} to be exported by ${modulePath}\`);
  }
}
for (const name of excludes) {
  if (Object.prototype.hasOwnProperty.call(mod, name)) {
    throw new Error(\`Expected \${name} not to be exported by ${modulePath}\`);
  }
}
`
  );
  assertNodeOutput(assertionPath, {
    expectedStdout: "",
  });
}

export function assertGeneratedModuleScript({ expectedStdout, outRoot, source }) {
  const assertionPath = join(outRoot, `assert_generated_module_${generatedModuleScriptCounter++}.mjs`);
  writeFileSync(assertionPath, source);
  assertNodeOutput(assertionPath, {
    expectedStdout,
  });
}

export function assertGeneratedModuleAfterEntryScript({ expectedStdout, outRoot, source }) {
  assertGeneratedModuleScript({
    expectedStdout,
    outRoot,
    source: `const __log = console.log;
console.log = () => {};
await import("./static/app/entry.js");
console.log = __log;
${source}`,
  });
}

function writeJsonFile(path, value) {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
}

export function assertNodeOutput(
  path,
  { expectedSignal = null, expectedStatus = 0, expectedStderr = "", expectedStdout }
) {
  assert.deepEqual(runNodeScript(path), {
    signal: expectedSignal,
    status: expectedStatus,
    stderr: expectedStderr,
    stdout: expectedStdout,
  });
}
