import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { dump } from "../parser.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import {
  arrow,
  binary,
  call,
  exportNamed,
  id,
  literal,
  lower,
  member,
  moduleEvaluationOrder,
  observe,
  sequentialSplit,
  program,
  property,
  variable,
} from "./harness.mjs";

const entry = "entry.mjs";
const owner = "owner.mjs";
const observer = "observer.mjs";
const oneCall = { [owner]: ["#0"], [observer]: ["#1"], [entry]: ["#2"] };

function publicSplit(name, source, modules = oneCall, order = [owner, observer]) {
  return sequentialSplit(name, source, modules, order);
}

function expectPublicRefusal({ verdict, log }, reasonCode) {
  assert.equal(verdict.status, "rejected", log);
  assert.equal(verdict.reason_code, reasonCode, log);
  assert.equal(verdict.guarantee, null, log);
}

function snapshot(directory) {
  return readdirSync(directory)
    .sort()
    .map((name) => {
      const file = path.join(directory, name);
      const { ino, mtimeNs } = statSync(file, { bigint: true });
      return [name, ino, mtimeNs, readFileSync(file)];
    });
}

function assertModel(files, directory, { status, output }) {
  const parse = (file) => dump(readFileSync(file, "utf8"), { includeOpaqueCaptures: true });
  const input = {
    source: parse(files.sourceFile),
    spec: readFileSync(files.specFile, "utf8"),
    files: Object.fromEntries(readdirSync(directory).map((name) => [name, parse(path.join(directory, name))])),
    export: "result",
  };
  const run = spawnSync(process.env.ARITHMETIC_OBSERVER_MODEL, [], {
    encoding: "utf8",
    input: JSON.stringify(input),
  });
  assert.equal(run.status, status, run.error?.message ?? run.stdout + run.stderr);
  assert.deepEqual(JSON.parse(run.stdout), output);
}

async function checkPreview(
  test,
  result,
  {
    order = [owner, observer],
    original = result,
    reasonCode = "no_compiled_rule",
    expectedExit = 0,
    modeled = { status: 0, output: { guarantee: "modeled-all-outcomes", original: result, split: result } },
  } = {}
) {
  const { files, out } = test;
  expectPublicRefusal(test, reasonCode);
  assert(!existsSync(out), "refusal created the requested output directory");
  assert.deepEqual(observe(files.sourceFile, "result"), { result: original });

  await withSplitPreview(
    { source: files.sourceFile, spec: files.specFile, expectedExit },
    ({ directory, entryFile }) => {
      assert.deepEqual(moduleEvaluationOrder(directory, entry), [...order, entry]);
      assert.deepEqual(observe(entryFile, "result"), { result });
      assertModel(files, directory, modeled);

      const before = snapshot(directory);
      const rechecked = lower(files.sourceFile, files.specFile, directory, ["--check-output"]);
      expectPublicRefusal(rechecked, reasonCode);
      assert.deepEqual(snapshot(directory), before, "--check-output modified the preview");
    }
  );
}

const position = `function position(index, values) {
  return values.length === 1 ? "single" : index === 0 ? "first" : index === values.length - 1 ? "last" : "middle";
}`;

// The exported Boolean records an eager call through the split's import.
await checkPreview(
  publicSplit(
    "position-observer",
    `${position}
    const result = position(2, { length: " 3 " }) === "last";
    export { result };`
  ),
  true
);

const lengthRead = member(id("values"), id("length"));

for (const [name, length, index, result] of [
  ["numeric-length", 3, 2, true],
  ["string-length", " 0x3 ", 2, true],
  ["strict-index", " 3 ", "2", false],
]) {
  const source = program([
    variable(
      "const",
      "isLast",
      arrow([id("index"), id("values")], binary("===", id("index"), binary("-", lengthRead, literal(1))))
    ),
    variable(
      "const",
      "result",
      call(id("isLast"), [
        literal(index),
        { type: "ObjectExpression", properties: [property("length", literal(length))] },
      ])
    ),
    exportNamed([["result", "result"]]),
  ]);
  await checkPreview(publicSplit(name, source), result);
}

// Both schedules finish. In the forced split, the eager call sees the hoisted
// length cell before the write, so its subtraction produces NaN.
{
  const source = `${position}
    var length;
    length = " 3 ";
    const result = position(2, { length }) === "last";
    export { result };`;
  const state = "state.mjs";
  const modules = { [owner]: ["#0"], [state]: ["#1", "#2"], [observer]: ["#3"], [entry]: ["#4"] };
  await checkPreview(publicSplit("after-length-write", source, modules, [owner, state, observer]), true, {
    order: [owner, state, observer],
  });

  const order = [owner, observer, state];
  const early = publicSplit("before-length-write", source, modules, order);
  const observation = { kind: "value", path: ["result"], original: "true", split: "false" };
  assert.deepEqual(early.verdict.observation, observation);
  await checkPreview(early, false, {
    order,
    original: true,
    reasonCode: "probe_mismatch",
    expectedExit: 1,
    modeled: { status: 1, output: { reason_code: "probe_mismatch", observation } },
  });
}
