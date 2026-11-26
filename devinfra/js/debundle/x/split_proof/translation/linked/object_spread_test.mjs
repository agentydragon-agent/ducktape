import assert from "node:assert/strict";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { prepareWorkerFixture } from "./fixture_preview.mjs";
import { observe } from "./harness.mjs";

const copied = prepareWorkerFixture(
  "object-spread",
  `const source = { id: 1, get label() { return this.id; } };
   class Row {
     get value() { return { ...source, id: 2 }; }
   }
   const copy = { ...new Row().value, ...null, label: 3 };
   export const result = [source.id, copy.id, copy.label];`,
  ["#1", "#2", "#3"]
);
assert.deepEqual(observe(copied.sourceFile, "result"), { result: [1, 2, 3] });
await withSplitPreview({ manifest: copied.manifest }, ({ entryFile }) => {
  assert.deepEqual(observe(entryFile, "result"), { result: [1, 2, 3] });
});

for (const [name, source, expected, reason] of [
  [
    "object-spread-error",
    `const run = () => { try { null.x; } catch (err) { return { ...err }; } };
     export const result = run();`,
    {},
    "object spread inspects an engine error",
  ],
  [
    "object-spread-supplementary",
    `const run = () => ({ ..."A😀" });
     export const result = run();`,
    { 0: "A", 1: "\ud83d", 2: "\ude00" },
    "object spread would copy an isolated UTF-16 surrogate",
  ],
]) {
  const fixture = prepareWorkerFixture(name, source);
  assert.deepEqual(observe(fixture.sourceFile, "result"), { result: expected });
  await withSplitPreview({ manifest: fixture.manifest }, ({ directory, entryFile }) => {
    assert.deepEqual(observe(entryFile, "result"), { result: expected });
    const model = probeLinkedModel({ source: fixture.sourceFile, spec: fixture.specFile, directory, observe: [] });
    assert.equal(model.status, "refused", JSON.stringify(model));
    assert.equal(model.reason_code, "probe_unknown");
    assert.equal(model.reason, `original reached an unknown result during linked initialization: ${reason}`);
  });
}
