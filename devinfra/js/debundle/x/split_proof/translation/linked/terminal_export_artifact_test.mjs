import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { dump } from "../parser.mjs";
import { split } from "../testing/split.mjs";
import { writeDeployment } from "../testing/deployment_manifest.mjs";
import { observe, prepare, root } from "./harness.mjs";

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

// Non-vacuity: the fixed input-side premises hold for a real parsed module.
const inputWitness = spawnSync(process.env.TERMINAL_CONST_INPUT_CHECKER, [], {
  encoding: "utf8",
  input: JSON.stringify(dump("const x = 1;\nexport { x };\n")),
});
assert.equal(inputWitness.status, 0, inputWitness.error?.message ?? inputWitness.stdout + inputWitness.stderr);

// This checks source admission alone: it neither emits nor certifies a split.
for (const [label, source, authored, accepted] of [
  ["one", "const x = 1;\nexport { x };\n", spec, true],
  ["nine", "const x = 9;\nexport { x };\n", spec, true],
  ["hashbang", "#!/usr/bin/env node\nconst x = 3;\nexport { x };\n", spec, true],
  ["wrong-name", "const a = 1;\nexport { a };\n", spec, false],
  [
    "wrong-owner",
    "const x = 1;\nexport { x };\n",
    { ...spec, modules: { [worker]: ["#0", "#1"], [entry]: [] } },
    false,
  ],
]) {
  const input = prepare(path.join(root, `source-${label}`), { source, provider: "", spec: authored });
  const unusedOut = path.join(root, `source-${label}-out`);
  const manifest = writeDeployment(input.sourceFile, input.specFile, unusedOut);
  const result = spawnSync(process.env.LOWERSPLIT, ["--check-source", manifest], { encoding: "utf8" });
  assert.equal(result.status, accepted ? 0 : 1, result.error?.message ?? result.stdout + result.stderr);
  if (accepted) {
    assert.equal(result.stdout.trim(), "source admitted");
    // Concrete diagnostic, not a premise of the source-to-model theorem.
    const emitted = spawnSync(process.env.LOWERSPLIT, ["--probe-emission", manifest], { encoding: "utf8" });
    assert.equal(emitted.status, 0, emitted.error?.message ?? emitted.stdout + emitted.stderr);
    assert.equal(emitted.stdout.trim(), "emitter example matched");
    // Uses Q's encoder, then the existing printer and exact disk reread gate.
    // The test-only diagnostic refuses publication even when the probe passes.
    const staged = spawnSync(process.env.LOWERSPLIT, ["--probe-codec-staging", manifest], { encoding: "utf8" });
    assert.equal(staged.status, 0, staged.error?.message ?? staged.stdout + staged.stderr);
    assert.equal(staged.stdout.trim(), "codec staged and reread");
  }
  assert(!existsSync(unusedOut));
}
