import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { split } from "../testing/split.mjs";
import { moduleEvaluationOrder, observe, prepare, root } from "./harness.mjs";

const entry = "entry.mjs";
const worker = "provider.mjs";
const spec = { entry, modules: { [worker]: ["#0"], [entry]: ["#1"] }, order: [worker], sequential: true };
const files = prepare(path.join(root, "terminal-export"), {
  source: "const a = 1;\nexport { a };\n",
  provider: "",
  spec,
});
const out = path.join(root, "terminal-export-out");
const run = (options = {}) =>
  split({ source: files.sourceFile, spec: files.specFile, out, require: "all-outcomes", ...options });
const original = run();
assert.equal(original.status, "certified", original.log);
assert.equal(original.guarantee, "all-outcomes");
assert.deepEqual(original.files, [entry, worker]);
assert.deepEqual(observe(files.sourceFile, "a"), { a: 1 });
assert.deepEqual(observe(path.join(out, entry), "a"), { a: 1 });
assert.equal(run({ checkOutput: true }).status, "certified");

const entryFile = path.join(out, entry);
const workerFile = path.join(out, worker);
const entryBytes = readFileSync(entryFile);
const workerBytes = readFileSync(workerFile);
writeFileSync(entryFile, "const decoy = 1; export { decoy as a };\n");
const wrongCellBytes = readFileSync(entryFile);
const badCell = run({ checkOutput: true, allowExistingOut: true });
assert.equal(badCell.status, "refused", badCell.log);
assert.deepEqual(readFileSync(entryFile), wrongCellBytes);
assert.deepEqual(readFileSync(workerFile), workerBytes);
writeFileSync(entryFile, entryBytes);

for (const [name, badSpec] of [
  ["wrong-owner", { ...spec, modules: { [worker]: ["#0", "#1"], [entry]: [] } }],
  ["wrong-ordinal", { ...spec, modules: { [worker]: ["#0"], [entry]: ["#2"] } }],
  ["duplicate-ordinal", { ...spec, modules: { [worker]: ["#0"], [entry]: ["#1", "#1"] } }],
  ["missing-export", { ...spec, modules: { [worker]: ["#0"], [entry]: [] } }],
]) {
  const badSpecFile = path.join(root, name + ".json");
  writeFileSync(badSpecFile, JSON.stringify(badSpec));
  const refused = run({ spec: badSpecFile, allowExistingOut: true });
  assert.equal(refused.status, "refused", refused.log);
  assert.doesNotMatch(refused.reason, /terminal-export-not-applicable/, refused.log);
  assert.deepEqual(readFileSync(entryFile), entryBytes);
  assert.deepEqual(readFileSync(workerFile), workerBytes);
  assert.deepEqual(readdirSync(out).sort(), [entry, worker].sort());
}

const fresh = path.join(root, "wrong-ordinal-fresh");
const badSpecFile = path.join(root, "wrong-ordinal.json");
assert.equal(run({ spec: badSpecFile, out: fresh }).status, "refused");
assert(!existsSync(fresh));

// A different valid source belongs to another strategy, not a refusal by this one.
const other = prepare(path.join(root, "other-source"), {
  source: "const a = 1;\nexport const b = 2;\n",
  provider: "",
  spec,
});
const otherOut = path.join(root, "other-source-out");
const otherResult = split({ source: other.sourceFile, spec: other.specFile, out: otherOut, require: "all-outcomes" });
assert.equal(otherResult.status, "refused", otherResult.log);
assert.match(otherResult.reason, /terminal-export-not-applicable/, otherResult.log);
assert(!existsSync(otherOut));

// Original ordinals include the terminal export list; providers and readers
// retain their authored owners and sequential import priority.
const multiSpec = {
  entry,
  modules: { "values.mjs": ["#0", "#1"], "readers.mjs": ["#2", "#3"], [entry]: ["#4"] },
  order: ["values.mjs", "readers.mjs"],
  sequential: true,
};
const multi = prepare(path.join(root, "multi-terminal-export"), {
  source: 'const a = "same";\nconst b = "same";\nconst first = a;\nconst second = b;\nexport { first, second };\n',
  provider: "",
  spec: multiSpec,
});
const multiOut = path.join(root, "multi-terminal-export-out");
const multiRun = (options = {}) =>
  split({ source: multi.sourceFile, spec: multi.specFile, out: multiOut, require: "all-outcomes", ...options });
const multiResult = multiRun();
assert.equal(multiResult.status, "certified", multiResult.log);
assert.deepEqual(observe(path.join(multiOut, entry), ["first", "second"]), { first: "same", second: "same" });
assert.deepEqual(moduleEvaluationOrder(multiOut, entry), [...multiSpec.order, entry]);
assert.equal(multiRun({ checkOutput: true }).status, "certified");
const multiFiles = [entry, "values.mjs", "readers.mjs"];
const saved = Object.fromEntries(multiFiles.map((name) => [name, readFileSync(path.join(multiOut, name))]));
const multiEntry = path.join(multiOut, entry);
const wrongMultiCell = saved[entry]
  .toString()
  .replace(/export\s*\{\s*first\s*,\s*second\s*\}/, "export { second as first, second }");
assert.notEqual(wrongMultiCell, saved[entry].toString());
writeFileSync(multiEntry, wrongMultiCell);
assert.deepEqual(observe(multiEntry, ["first", "second"]), { first: "same", second: "same" });
const wrongMultiBytes = readFileSync(multiEntry);
const wrongMultiResult = multiRun({ checkOutput: true, allowExistingOut: true });
assert.equal(wrongMultiResult.status, "refused", wrongMultiResult.log);
assert.deepEqual(readFileSync(multiEntry), wrongMultiBytes);
for (const file of ["values.mjs", "readers.mjs"])
  assert.deepEqual(readFileSync(path.join(multiOut, file)), saved[file]);
writeFileSync(multiEntry, saved[entry]);
for (const [name, badSpec] of [
  [
    "multi-wrong-owner",
    { ...multiSpec, modules: { "values.mjs": ["#0", "#1", "#4"], "readers.mjs": ["#2", "#3"], [entry]: [] } },
  ],
  ["multi-missing-metadata", { ...multiSpec, modules: { ...multiSpec.modules, [entry]: [] } }],
  ["multi-duplicate-metadata", { ...multiSpec, modules: { ...multiSpec.modules, [entry]: ["#4", "#4"] } }],
  ["multi-reordered", { ...multiSpec, order: ["readers.mjs", "values.mjs"] }],
]) {
  const badSpecFile = path.join(root, name + ".json");
  writeFileSync(badSpecFile, JSON.stringify(badSpec));
  const result = multiRun({ spec: badSpecFile, allowExistingOut: true });
  assert.equal(result.status, "refused", result.log);
  for (const file of multiFiles) assert.deepEqual(readFileSync(path.join(multiOut, file)), saved[file]);
}

const count = 16;
const names = Array.from({ length: count }, (_, i) => `reader${i}`);
const graphSource = [
  ...names.map((_, i) => `const data${i} = "value${i}";`),
  ...names.map((name, i) => `const ${name} = data${i};`),
  `export { ${names.join(", ")} };`,
].join("\n");
const graphModules = {};
for (const [group, offset] of [
  ["provider", 0],
  ["consumer", count],
]) {
  for (let i = 0; i < count; i++) (graphModules[`${group}${Math.floor(i / 8)}.mjs`] ??= []).push(`#${offset + i}`);
}
const graphOrder = Object.keys(graphModules);
graphModules[entry] = ["#32"];
const graph = prepare(path.join(root, "multi-terminal-graph"), {
  source: graphSource,
  provider: "",
  spec: { entry, modules: graphModules, order: graphOrder, sequential: true },
});
const graphOut = path.join(root, "multi-terminal-graph-out");
const graphResult = split({ source: graph.sourceFile, spec: graph.specFile, out: graphOut, require: "all-outcomes" });
assert.equal(graphResult.status, "certified", graphResult.log);
assert.deepEqual(moduleEvaluationOrder(graphOut, entry), [...graphOrder, entry]);
assert.deepEqual(
  observe(path.join(graphOut, entry), names),
  Object.fromEntries(names.map((name, i) => [name, `value${i}`]))
);

const renamed = prepare(path.join(root, "multi-terminal-renamed"), {
  source:
    'const a = "same";\nconst b = "same";\nconst first = a;\nconst second = b;\nexport { first as renamed, second };\n',
  provider: "",
  spec: multiSpec,
});
const renamedResult = split({
  source: renamed.sourceFile,
  spec: renamed.specFile,
  out: path.join(root, "multi-terminal-renamed-out"),
  require: "all-outcomes",
});
assert.equal(renamedResult.status, "refused", renamedResult.log);
