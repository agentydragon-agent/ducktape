import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { dump } from "../parser.mjs";
import { split } from "../testing/split.mjs";
import { forcePreview, moduleEvaluationOrder, observe, sequentialSplit } from "./harness.mjs";

const entry = "entry.mjs";
const owner = "owner.mjs";
const observer = "observer.mjs";
const state = "state.mjs";
const position = `function position(index, values) {
  return values.length === 1 ? "single" : index === 0 ? "first" : index === values.length - 1 ? "last" : "middle";
}`;
const parse = (file) => dump(readFileSync(file, "utf8"), { includeOpaqueCaptures: true });

function checkModel({ files }, preview, status) {
  const input = {
    source: parse(files.sourceFile),
    spec: readFileSync(files.specFile, "utf8"),
    files: Object.fromEntries(readdirSync(preview).map((name) => [name, parse(path.join(preview, name))])),
    export: "result",
  };
  const run = spawnSync(process.env.LINKED_MODEL_CHECKER, [], {
    encoding: "utf8",
    input: JSON.stringify(input),
  });
  assert.equal(run.status, status, run.error?.message ?? run.stdout + run.stderr);
  return JSON.parse(run.stdout);
}

const positive = sequentialSplit(
  "position-observer",
  `${position}
    const result = position(2, { length: " 3 " }) === "last";
    export { result };`,
  { [owner]: ["#0"], [observer]: ["#1"], [entry]: ["#2"] },
  [owner, observer]
);

// The ordinary publication command refuses this source with either a fresh or an existing destination.
const assertStrictRefusal = (verdict, log) => {
  assert.equal(verdict.status, "rejected", log);
  assert.equal(verdict.reason_code, "strict_observation_unsupported", log);
  assert.equal(verdict.guarantee, null, log);
  assert.equal(verdict.every_ending_matches, false, log);
};
assertStrictRefusal(positive.verdict, positive.log);
assert(!existsSync(positive.out));
const prior = Buffer.from("export const result = false;\n");
mkdirSync(positive.out);
writeFileSync(path.join(positive.out, entry), prior);
const existing = split({
  source: positive.files.sourceFile,
  spec: positive.files.specFile,
  out: positive.out,
  allowExistingOut: true,
});
assertStrictRefusal(existing.verdict, existing.log);
assert.deepEqual(readdirSync(positive.out), [entry]);
assert.deepEqual(readFileSync(path.join(positive.out, entry)), prior);

// Only the existing diagnostic command produces these scratch files. The checker consumes
// their Acorn Programs and returns a modeled initialization result without writing modules.
const preview = path.join(positive.dir, "preview");
forcePreview(positive.files, preview);
assert.deepEqual(moduleEvaluationOrder(preview, entry), [owner, observer, entry]);
assert.deepEqual(checkModel(positive, preview, 0), {
  guarantee: "modeled-all-outcomes",
  original: true,
  split: true,
});
assert.deepEqual(observe(positive.files.sourceFile, "result"), { result: true });
assert.deepEqual(observe(path.join(preview, entry), "result"), { result: true });

// The altered schedule calls position before the length write. Both executions
// finish, but reading undefined in the split makes the subtraction produce NaN.
const earlyOrder = [owner, observer, state];
const early = sequentialSplit(
  "before-length-write",
  `${position}
    var length;
    length = " 3 ";
    const result = position(2, { length }) === "last";
    export { result };`,
  { [owner]: ["#0"], [state]: ["#1", "#2"], [observer]: ["#3"], [entry]: ["#4"] },
  earlyOrder
);
const earlyPreview = path.join(early.dir, "preview");
forcePreview(early.files, earlyPreview);
assert.deepEqual(moduleEvaluationOrder(earlyPreview, entry), [...earlyOrder, entry]);
assert.deepEqual(checkModel(early, earlyPreview, 1), {
  reason_code: "probe_mismatch",
  observation: { kind: "value", path: ["result"], original: "true", split: "false" },
});
assert.deepEqual(observe(early.files.sourceFile, "result"), { result: true });
assert.deepEqual(observe(path.join(earlyPreview, entry), "result"), { result: false });
