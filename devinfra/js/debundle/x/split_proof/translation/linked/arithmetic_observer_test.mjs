import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import path from "node:path";
import {
  arrow,
  binary,
  call,
  exportNamed,
  forcePreview,
  id,
  literal,
  member,
  moduleEvaluationOrder,
  observe,
  runLinkedCoreJSModel,
  sequentialSplit,
  program,
  property,
  variable,
} from "./harness.mjs";

const entry = "entry.mjs";
const owner = "owner.mjs";
const observer = "observer.mjs";
const oneCall = { [owner]: ["#0"], [observer]: ["#1"], [entry]: ["#2"] };

function split(name, source, modules = oneCall, order = [owner, observer]) {
  return sequentialSplit(name, source, modules, order);
}

function assertModeledPositive(result, expected, moduleOrder = [owner, observer]) {
  assert.equal(result.verdict.status, "rejected", result.log);
  assert.equal(result.verdict.reason_code, "strict_observation_unsupported", result.log);
  assert.equal(result.verdict.guarantee, null, result.log);
  assert.equal(result.verdict.every_ending_matches, false, result.log);
  assert(!existsSync(result.out), result.out);
  const preview = path.join(result.dir, "preview");
  forcePreview(result.files, preview);
  assert.deepEqual(moduleEvaluationOrder(preview, entry), [...moduleOrder, entry]);
  assert.deepEqual(runLinkedCoreJSModel(result.files, preview), {
    guarantee: "modeled-all-outcomes",
    original: expected,
    split: expected,
  });
  for (const file of [result.files.sourceFile, path.join(preview, entry)])
    assert.deepEqual(observe(file, "result"), { result: expected }, file);
}

const position = `function position(index, values) {
  return values.length === 1 ? "single" : index === 0 ? "first" : index === values.length - 1 ? "last" : "middle";
}`;

// The exported Boolean records an eager call through the split's import.
assertModeledPositive(
  split(
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
  assertModeledPositive(split(name, source), result);
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
  assertModeledPositive(split("after-length-write", source, modules, [owner, state, observer]), true, [
    owner,
    state,
    observer,
  ]);

  const order = [owner, observer, state];
  const early = split("before-length-write", source, modules, order);
  assert.equal(early.verdict.status, "rejected", early.log);
  assert.equal(early.verdict.reason_code, "probe_mismatch", early.log);
  assert.equal(early.verdict.guarantee, null, early.log);
  assert.equal(early.verdict.every_ending_matches, false, early.log);
  assert.match(early.verdict.reason, /probe executions completed normally with different final states/, early.log);
  assert(!existsSync(early.out));
  const preview = path.join(early.dir, "preview");
  forcePreview(early.files, preview);
  assert.deepEqual(moduleEvaluationOrder(preview, entry), [...order, entry]);
  assert.deepEqual(runLinkedCoreJSModel(early.files, preview, "result", 1), {
    reason_code: "probe_mismatch",
    observation: { kind: "value", path: ["result"], original: "true", split: "false" },
  });
  assert.deepEqual(observe(early.files.sourceFile, "result"), { result: true });
  assert.deepEqual(observe(path.join(preview, entry), "result"), { result: false });
}
