import assert from "node:assert/strict";
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { split } from "../testing/split.mjs";
import { observe, prepare, root } from "./harness.mjs";

const entry = "entry.mjs";
const worker = "worker.mjs";
const source = "const seed = 42;\nexport { seed as exposed };\nconst result = seed;\n";
// The metadata at source ordinal 1 is omitted from the executable CoreJS units.
const spec = { entry, modules: { [worker]: ["#0"], [entry]: ["#2"] } };
const fixture = prepare(path.join(root, "positive"), { source, provider: "", spec });
const out = path.join(root, "out");
const run = (options = {}) =>
  split({ source: fixture.sourceFile, spec: fixture.specFile, out, require: "all-outcomes", ...options });
const snapshot = (directory) =>
  readdirSync(directory)
    .sort()
    .map((name) => [name, readFileSync(path.join(directory, name))]);
const emitted = run();
assert.equal(emitted.status, "certified", emitted.log);
assert.equal(emitted.verdict.strategy, "compiled-sparse-constructor", emitted.log);
assert.equal(emitted.verdict.guarantee, "all-outcomes", emitted.log);
assert.equal(emitted.verdict.every_ending_matches, true, emitted.log);
assert.equal(emitted.verdict.observation_scope, "strict-static-data", emitted.log);
assert.deepEqual(emitted.verdict.premises, []);
assert.deepEqual(emitted.files, [entry, worker]);
assert.deepEqual(observe(fixture.sourceFile, "exposed"), { exposed: 42 });
assert.deepEqual(observe(path.join(out, entry), "exposed"), { exposed: 42 });
const phases = (text) =>
  text
    .trim()
    .split("\n")
    .filter((line) => line.includes('"phase":'))
    .map((line) => JSON.parse(line).phase);
assert(phases(emitted.stderr).includes("checked_placement"), emitted.log);
assert(phases(emitted.stderr).includes("checked_correspondence"), emitted.log);
assert(!phases(emitted.stderr).includes("certificate_preparation"), emitted.log);
const checked = run({ checkOutput: true });
assert.deepEqual(checked.verdict, emitted.verdict);
assert(!phases(checked.stderr).includes("output_publication"), checked.log);

const entryFile = path.join(out, entry);
const original = readFileSync(entryFile, "utf8");
const wrongCell = original.replace(/export\s*\{\s*seed\s+as\s+exposed\s*\}/, "export { result as exposed }");
assert.notEqual(wrongCell, original);
writeFileSync(entryFile, wrongCell);
assert.deepEqual(observe(entryFile, "exposed"), { exposed: 42 });
const changed = snapshot(out);
const wrong = run({ checkOutput: true, allowExistingOut: true });
assert.equal(wrong.status, "refused", wrong.log);
assert.deepEqual(snapshot(out), changed, "wrong-cell refusal changed existing files");
writeFileSync(entryFile, original);

const longer = prepare(path.join(root, "longer"), {
  source: "const seed = 9;\nexport { seed as exposed };\nexport {};\nexport {};\nconst result = seed;\n",
  provider: "",
  spec: { entry, modules: { [worker]: ["#0"], [entry]: ["#4"] } },
});
const longerOut = path.join(root, "longer-out");
const longerResult = split({
  source: longer.sourceFile,
  spec: longer.specFile,
  out: longerOut,
  require: "all-outcomes",
});
assert.equal(longerResult.status, "certified", longerResult.log);
assert.deepEqual(observe(path.join(longerOut, entry), "exposed"), { exposed: 9 });

for (const [name, badSource, expected] of [
  [
    "non-metadata",
    "const seed = 42;\ndebugger;\nconst result = seed;\nexport { seed as exposed };\n",
    /unsupported omitted source node 1/,
  ],
  ["call", "const seed = Number(42);\nexport { seed as exposed };\nconst result = seed;\n", null],
  ["tdz", "const seed = result;\nexport { seed as exposed };\nconst result = 42;\n", null],
  ["stack", "const seed = 42;\nexport { seed as exposed };\nconst result = Error().stack;\n", null],
  ["throw", "const seed = 42;\nexport { seed as exposed };\nthrow new Error('stop');\nconst result = seed;\n", null],
  ["reflection", "const seed = 42;\nexport { seed as exposed };\nconst result = Object.keys(globalThis);\n", null],
]) {
  const bad = prepare(path.join(root, name), { source: badSource, provider: "", spec });
  const badOut = path.join(root, `${name}-out`);
  mkdirSync(badOut, { recursive: true });
  writeFileSync(path.join(badOut, entry), "previous output\n");
  const before = snapshot(badOut);
  const refused = split({
    source: bad.sourceFile,
    spec: bad.specFile,
    out: badOut,
    require: "all-outcomes",
    allowExistingOut: true,
  });
  assert.equal(refused.status, "refused", refused.log);
  assert.equal(refused.verdict.guarantee, null, refused.log);
  if (expected) assert.match(refused.verdict.reason, expected);
  assert.deepEqual(snapshot(badOut), before, `${name} refusal changed existing files`);
}

const reordered = prepare(path.join(root, "reordered"), {
  source,
  provider: "",
  spec: { entry, modules: { [worker]: ["#2"], [entry]: ["#0"] } },
});
const beforeReorder = snapshot(out);
const refusedReorder = split({
  source: reordered.sourceFile,
  spec: reordered.specFile,
  out,
  require: "all-outcomes",
  allowExistingOut: true,
});
assert.equal(refusedReorder.status, "refused", refusedReorder.log);
assert.match(refusedReorder.verdict.reason, /changes the source unit order/);
assert.deepEqual(snapshot(out), beforeReorder, "reorder refusal changed existing files");

const contract = path.join(root, "browser-contract.json");
writeFileSync(contract, JSON.stringify({ profile: "browser-page" }));
for (const options of [{ structural: true }, { hostContract: contract }]) {
  const before = snapshot(out);
  const refused = run({ ...options, allowExistingOut: true });
  assert.equal(refused.status, "refused", refused.log);
  assert.equal(refused.verdict.guarantee, null, refused.log);
  assert.match(refused.verdict.reason, /does not support host or deployment options/);
  assert.deepEqual(snapshot(out), before, "option refusal changed existing files");
}
