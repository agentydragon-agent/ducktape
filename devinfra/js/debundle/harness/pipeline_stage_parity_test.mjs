import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("vendor boundary rename parity through write_js_tree", () => {
  const fixture = createFixture("debundle-vendor-rename-parity-");
  writeSnapshotFixture(fixture, {
    "static/vendor.js": `const internal = 7;\nexport { internal as publicName };\n`,
    "static/consumer.js": `import { internal as aliased } from "./vendor.js";\nconsole.log("value:" + aliased);\n`,
  });
  const operations = [
    {
      id: "vendor_public",
      operation: "mark_vendor",
      level: "boundary-rename",
      chunkPath: "static/vendor.js",
      identity: "fixture-vendor",
      evidence: [{ kind: "fixture" }],
    },
  ];
  const spec = baseSpec(fixture, operations, [
    "load_js_chunks",
    "compute_js_asts",
    "normalize_js_chunks",
    "apply_vendor_annotations",
    "rename_vendor_exports",
    "rewrite_chunk_entry_specifiers",
    "write_js_tree",
  ]);

  const js = runImpl("js", fixture, spec);
  const rust = runImpl("rust", fixture, spec);
  assert.deepEqual(js.steps, rust.steps);
  assert.equal(runNode(join(js.outRoot, "static", "consumer", "entry.js")).stdout.trim(), "value:7");
  assert.equal(runNode(join(rust.outRoot, "static", "consumer", "entry.js")).stdout.trim(), "value:7");
  assert.match(readFileSync(join(js.outRoot, "static", "consumer", "entry.js"), "utf8"), /publicName/);
  assert.match(readFileSync(join(rust.outRoot, "static", "consumer", "entry.js"), "utf8"), /publicName/);
});

test("vendor swap parity records resolution and removes swapped chunk", () => {
  const fixture = createFixture("debundle-vendor-swap-parity-");
  writeSnapshotFixture(fixture, {
    "static/vendor.js": `export const left = 1;\n`,
  });
  const packageRoot = join(fixture.root, "pkg");
  mkdirSync(packageRoot, { recursive: true });
  writeFileSync(
    join(packageRoot, "package.json"),
    `${JSON.stringify({ name: "fixture-pkg", version: "1.2.3" }, null, 2)}\n`
  );
  writeFileSync(join(packageRoot, "index.js"), `export const left = 1;\nexport const right = 2;\n`);
  const operations = [
    {
      id: "vendor_swap",
      operation: "mark_vendor",
      level: "swap",
      chunkPath: "static/vendor.js",
      identity: "fixture-vendor",
      evidence: [{ kind: "fixture" }],
      package: "fixture-pkg",
      version: "1.2.3",
      subpath: "index.js",
    },
  ];
  const spec = baseSpec(fixture, operations, [
    "load_js_chunks",
    "compute_js_asts",
    "normalize_js_chunks",
    "apply_vendor_annotations",
    "rename_vendor_exports",
    {
      operation: "swap_vendor_chunks",
      args: {
        outputManifestPath: join(fixture.outRoot, "vendor-resolution.json"),
      },
    },
    "write_js_tree",
  ]);

  const js = runImpl("js", fixture, spec, ["--package-root", `fixture-pkg=${packageRoot}`]);
  const rust = runImpl("rust", fixture, spec, ["--package-root", `fixture-pkg=${packageRoot}`]);
  assert.deepEqual(js.steps, rust.steps);
  assert.deepEqual(
    JSON.parse(readFileSync(rust.vendorResolutionPath, "utf8")),
    JSON.parse(readFileSync(js.vendorResolutionPath, "utf8"))
  );
  assert.equal(existsSync(join(js.outRoot, "static", "vendor")), false);
  assert.equal(existsSync(join(rust.outRoot, "static", "vendor")), false);
  assert.equal(JSON.parse(readFileSync(join(js.outRoot, "manifest.json"), "utf8")).counts.chunks, 0);
  assert.equal(JSON.parse(readFileSync(join(rust.outRoot, "manifest.json"), "utf8")).counts.chunks, 0);
});

test("logical materialization parity preserves runtime behavior through write_js_tree", () => {
  const fixture = createFixture("debundle-logical-parity-");
  writeSnapshotFixture(fixture, {
    "static/app.js": `function helper() { return "h"; }\nfunction run() { return helper() + "!"; }\nconsole.log(run());\nexport { run };\n`,
  });
  const operations = [
    {
      id: "logical_run",
      operation: "define_logical_module",
      selector: { chunkId: "static/app" },
      target: { path: "features/run" },
      members: [
        {
          id: "member_run",
          name: "run",
          selector: { binding: { kind: "FunctionDeclaration", name: "run" } },
        },
      ],
    },
    {
      id: "logical_residual",
      operation: "define_residual_module",
      selector: { chunkId: "static/app" },
      target: { path: "residual/unhandled" },
    },
  ];
  const spec = baseSpec(fixture, operations, [
    "load_js_chunks",
    "compute_js_asts",
    "normalize_js_chunks",
    {
      operation: "materialize_logical_modules",
      args: {
        chunkIds: ["static/app"],
        pruneOtherChunks: false,
      },
    },
    "write_js_tree",
  ]);

  const js = runImpl("js", fixture, spec);
  const rust = runImpl("rust", fixture, spec);
  assert.deepEqual(js.steps, rust.steps);
  assert.equal(runNode(join(js.outRoot, "static", "app", "entry.js")).stdout.trim(), "h!");
  assert.equal(runNode(join(rust.outRoot, "static", "app", "entry.js")).stdout.trim(), "h!");
  assert.equal(existsSync(join(js.outRoot, "static", "app", "modules", "features", "run.js")), true);
  assert.equal(existsSync(join(rust.outRoot, "static", "app", "modules", "features", "run.js")), true);
});

test("logical materialization parity preserves object-pattern default references after readable naturalization", () => {
  const fixture = createFixture("debundle-logical-default-reference-parity-");
  writeSnapshotFixture(fixture, {
    "static/app.js": `function z() { return "z"; }
const b = ({ p: c }) => c;
const f = ({ x: a = b }) => a({ p: "p" });
const g = f({ x: b });
console.log(f({}) + g + z());
export { b, f, z };
`,
  });
  const operations = [
    {
      id: "logical_z",
      operation: "define_logical_module",
      selector: { chunkId: "static/app" },
      target: { path: "features/z" },
      members: [
        {
          id: "member_z",
          name: "z",
          selector: { binding: { kind: "FunctionDeclaration", name: "z" } },
        },
      ],
    },
  ];
  const spec = baseSpec(fixture, operations, [
    "load_js_chunks",
    "compute_js_asts",
    "normalize_js_chunks",
    {
      operation: "materialize_logical_modules",
      args: {
        chunkIds: ["static/app"],
        pruneOtherChunks: false,
      },
    },
    "write_js_tree",
  ]);

  const js = runImpl("js", fixture, spec);
  const rust = runImpl("rust", fixture, spec);
  assert.deepEqual(js.steps, rust.steps);
  assert.equal(runNode(join(js.outRoot, "static", "app", "entry.js")).stdout.trim(), "ppz");
  assert.equal(runNode(join(rust.outRoot, "static", "app", "entry.js")).stdout.trim(), "ppz");
  assert.doesNotMatch(readFileSync(join(js.outRoot, "static", "app", "entry.js"), "utf8"), /x\s*=\s*x/);
  assert.doesNotMatch(readFileSync(join(rust.outRoot, "static", "app", "entry.js"), "utf8"), /x\s*=\s*x/);
});

test("logical materialization parity preserves residual var-chain default references", () => {
  const fixture = createFixture("debundle-logical-var-chain-default-reference-parity-");
  writeSnapshotFixture(fixture, {
    "static/app.js": `function z() { return "z"; }
function m() { return "m"; }
var b = ({ p: c }) => c,
  f = ({ x: a = b }) => ({
    y: a,
    execute: () => {
      return a({ p: "p" }) + m();
    }
  }),
  g = f({ x: b });
console.log(g.execute() + "|" + f({ q: 1 }).execute());
export { b, f, m, z };
`,
  });
  const operations = [
    {
      id: "logical_z",
      operation: "define_logical_module",
      selector: { chunkId: "static/app" },
      target: { path: "features/z" },
      members: [
        {
          id: "member_z",
          name: "z",
          selector: { binding: { kind: "FunctionDeclaration", name: "z" } },
        },
      ],
    },
  ];
  const spec = baseSpec(fixture, operations, [
    "load_js_chunks",
    "compute_js_asts",
    "normalize_js_chunks",
    {
      operation: "materialize_logical_modules",
      args: {
        chunkIds: ["static/app"],
        pruneOtherChunks: false,
      },
    },
    "write_js_tree",
  ]);

  const js = runImpl("js", fixture, spec);
  const rust = runImpl("rust", fixture, spec);
  assert.deepEqual(js.steps, rust.steps);
  assert.equal(runNode(join(js.outRoot, "static", "app", "entry.js")).stdout.trim(), "pm|pm");
  assert.equal(runNode(join(rust.outRoot, "static", "app", "entry.js")).stdout.trim(), "pm|pm");
  assert.doesNotMatch(readFileSync(join(js.outRoot, "static", "app", "entry.js"), "utf8"), /x\s*=\s*x/);
  assert.doesNotMatch(readFileSync(join(rust.outRoot, "static", "app", "entry.js"), "utf8"), /x\s*=\s*x/);
});

test("logical materialization parity keeps reserved property aliases as explicit aliases", () => {
  const fixture = createFixture("debundle-logical-reserved-alias-parity-");
  writeSnapshotFixture(fixture, {
    "static/app.js": `async function f() {
  const { default: a } = await Promise.resolve({ default: "p" });
  return a;
}
console.log(await f());
export { f };
`,
  });
  const operations = [
    {
      id: "logical_f",
      operation: "define_logical_module",
      selector: { chunkId: "static/app" },
      target: { path: "features/f" },
      members: [
        {
          id: "member_f",
          name: "f",
          selector: { binding: { kind: "FunctionDeclaration", name: "f" } },
        },
      ],
    },
  ];
  const spec = baseSpec(fixture, operations, [
    "load_js_chunks",
    "compute_js_asts",
    "normalize_js_chunks",
    {
      operation: "materialize_logical_modules",
      args: {
        chunkIds: ["static/app"],
        pruneOtherChunks: false,
      },
    },
    "write_js_tree",
  ]);

  const js = runImpl("js", fixture, spec);
  const rust = runImpl("rust", fixture, spec);
  assert.deepEqual(js.steps, rust.steps);
  assert.equal(runNode(join(js.outRoot, "static", "app", "entry.js")).stdout.trim(), "p");
  assert.equal(runNode(join(rust.outRoot, "static", "app", "entry.js")).stdout.trim(), "p");
  assert.doesNotMatch(
    readFileSync(join(js.outRoot, "static", "app", "modules", "features", "f.js"), "utf8"),
    /default\s*}/
  );
  assert.doesNotMatch(
    readFileSync(join(rust.outRoot, "static", "app", "modules", "features", "f.js"), "utf8"),
    /default\s*}/
  );
});

function baseSpec(fixture, operations, operationsPipeline) {
  const pipeline = operationsPipeline.map((entry, index) => {
    const operation = typeof entry === "string" ? entry : entry.operation;
    const args = typeof entry === "string" ? {} : (entry.args ?? {});
    if (operation === "load_js_chunks") {
      return {
        id: `stage_${index}_${operation}`,
        operation,
        args: {
          inputRoot: fixture.snapshotRoot,
          jsListPath: fixture.jsListPath,
        },
      };
    }
    if (operation === "write_js_tree") {
      return {
        id: `stage_${index}_${operation}`,
        operation,
        args: {
          force: true,
          outDir: fixture.outRoot,
          ...args,
        },
      };
    }
    return {
      id: `stage_${index}_${operation}`,
      operation,
      ...(Object.keys(args).length > 0 ? { args } : {}),
    };
  });
  return {
    kind: "js.ast_transform_spec",
    operations,
    pipeline,
  };
}

function createFixture(prefix) {
  const root = mkdtemp(prefix);
  return {
    root,
    snapshotRoot: join(root, "snapshot"),
    extractedRoot: join(root, "extracted"),
    outRoot: join(root, "out"),
    jsListPath: join(root, "extracted", "js-files.txt"),
  };
}

function mkdtemp(prefix) {
  const path = join(tmpdir(), `${prefix}${process.pid}-${Math.random().toString(16).slice(2)}`);
  rmSync(path, { recursive: true, force: true });
  mkdirSync(path, { recursive: true });
  return path;
}

function writeSnapshotFixture(fixture, files) {
  mkdirSync(fixture.snapshotRoot, { recursive: true });
  mkdirSync(fixture.extractedRoot, { recursive: true });
  for (const [path, code] of Object.entries(files)) {
    const fullPath = join(fixture.snapshotRoot, path);
    mkdirSync(join(fullPath, ".."), { recursive: true });
    writeFileSync(fullPath, code);
  }
  writeFileSync(fixture.jsListPath, `${Object.keys(files).sort().join("\n")}\n`);
}

function runImpl(impl, fixture, spec, extraArgs = []) {
  const specPath = join(fixture.root, `${impl}-spec.json`);
  const outRoot = join(fixture.root, impl);
  const vendorResolutionPath = join(fixture.root, `${impl}-vendor-resolution.json`);
  const implSpec = {
    ...spec,
    pipeline: spec.pipeline.map((stage) =>
      stage.operation === "write_js_tree"
        ? { ...stage, args: { ...stage.args, outDir: outRoot } }
        : stage.operation === "swap_vendor_chunks"
          ? {
              ...stage,
              args: {
                ...stage.args,
                outputManifestPath: vendorResolutionPath,
              },
            }
          : stage
    ),
  };
  writeFileSync(specPath, `${JSON.stringify(implSpec, null, 2)}\n`);
  const run = spawnSync(resolveBin(impl), ["--spec", specPath, ...extraArgs], { encoding: "utf8" });
  assert.equal(run.status, 0, `${impl} failed:\nstdout:\n${run.stdout}\nstderr:\n${run.stderr}`);
  return {
    outRoot,
    vendorResolutionPath,
    stdout: run.stdout,
    steps: parseSteps(run.stdout),
  };
}

function resolveBin(impl) {
  const runfiles = process.env.TEST_SRCDIR;
  const workspace = process.env.TEST_WORKSPACE;
  assert.ok(runfiles && workspace, "bazel runfiles env missing");
  const envName = impl === "js" ? "JS_DEBUNDLE_BIN" : "RUST_DEBUNDLE_BIN";
  const rel = process.env[envName];
  assert.ok(rel, `${envName} missing`);
  return join(runfiles, workspace, rel);
}

function parseSteps(stdout) {
  return stdout
    .split("\n")
    .filter((line) => line.startsWith("- "))
    .map((line) => {
      const match = /^- ([^:]+): ([^ ]+) /.exec(line);
      assert.ok(match, `unexpected step summary line: ${line}`);
      return match[2];
    });
}

function runNode(path) {
  const result = spawnSync(process.execPath, [path], { encoding: "utf8" });
  assert.equal(result.status, 0, `node ${path} failed:\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
  return result;
}
