import assert from "node:assert/strict";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { assertMatchedModel, prepareLinkedFixture } from "./fixture_preview.mjs";
import { observe } from "./harness.mjs";

function fixture(name, source, moved, kept) {
  return prepareLinkedFixture(name, source, {
    entry: "entry.mjs",
    modules: { "entry.mjs": kept, "scroll.mjs": moved },
  });
}

const closed = fixture(
  "closed-template",
  'var marker = 0; var pattern = `^[^${"a" + "z"}]*[${"b"}]`; export { pattern };',
  ["#1"],
  ["#0", "#2"]
);
assertPublicEmissionRefused(closed.manifest, closed.out);
await withSplitPreview({ manifest: closed.manifest }, ({ directory, entryFile }) => {
  const pattern = "^[^az]*[b]";
  for (const file of [closed.sourceFile, entryFile]) {
    assert.deepEqual(observe(file, "pattern"), { pattern });
  }
  assertMatchedModel(closed, directory, [[["pattern"], pattern]]);
  assertPublicEmissionRefused(closed.manifest, directory);
  assertPublicRecheckRefused(closed.manifest, directory);
});

// A string declaration somewhere in the program is not a proof of what this
// cell contains at the read. Moving just the read observes undefined.
for (const [name, before, expression, expected, moved, expectedExit] of [
  ["prefix", 'export var parts = "a"', "`[${parts}]`", { result: "[a]" }, { result: "[undefined]" }, 1],
  [
    "getter",
    'export var parts = { get text() { return "b"; } }',
    "`[${parts.text}]`",
    { result: "[b]" },
    { error: "TypeError" },
    1,
  ],
  [
    "coercion",
    "export var parts = { toString() { throw new RangeError(); } }",
    "`[${parts}]`",
    { error: "RangeError" },
    { result: "[undefined]" },
    1,
  ],
  ["ordinary-construction", "var marker = 0", 'new RegExp("a")', { result: {} }, { result: {} }, 0],
  ["invalid-pattern", "var marker = 0", 'new RegExp("[")', { error: "SyntaxError" }, { error: "SyntaxError" }, 0],
  [
    "patched-constructor",
    "globalThis.RegExp = class { constructor() { throw new RangeError(); } }",
    'new RegExp("a")',
    { error: "RangeError" },
    { result: {} },
    1,
  ],
  [
    "shadow",
    "export var RegExp = class { constructor() { throw new TypeError(); } }",
    'new RegExp("a")',
    { error: "TypeError" },
    { error: "TypeError" },
    0,
  ],
]) {
  const test = fixture(name, `${before}; var result = ${expression}; export { result };`, ["#1"], ["#0", "#2"]);
  const { manifest, out, sourceFile, specFile } = test;
  assertPublicEmissionRefused(manifest, out);
  assert.deepEqual(observe(sourceFile, "result"), expected, name);
  await withSplitPreview({ manifest, expectedExit }, ({ directory, entryFile }) => {
    assert.deepEqual(observe(entryFile, "result"), moved, name);
    if (name === "prefix") {
      const model = probeLinkedModel({ source: sourceFile, spec: specFile, directory });
      assert.equal(model.status, "refused", JSON.stringify(model));
      assert.equal(model.reason_code, "probe_mismatch", JSON.stringify(model));
      assert.deepEqual(model.observation, {
        kind: "value",
        path: ["result"],
        original: '"[a]"',
        split: '"[undefined]"',
      });
    }
  });
}

// Reusing a compiled RegExp object (or copying the constructor input into
// .source) would fail these ordinary observations, even with a stable callee.
const fresh = fixture(
  "regexp-constructor-results",
  'var marker = 0; var first = new RegExp("a/b"); var second = new RegExp("a/b"); const inspect = () => { first.lastIndex = 3; return [first === second, first.source, second.lastIndex, new RegExp("").source]; }; export { inspect };',
  ["#1", "#2"],
  ["#0", "#3", "#4"]
);
assertPublicEmissionRefused(fresh.manifest, fresh.out);
const expected = { inspect: [false, "a\\/b", 0, "(?:)"] };
assert.deepEqual(observe(fresh.sourceFile, "inspect"), expected);
await withSplitPreview({ manifest: fresh.manifest }, ({ entryFile }) => {
  assert.deepEqual(observe(entryFile, "inspect"), expected);
});
