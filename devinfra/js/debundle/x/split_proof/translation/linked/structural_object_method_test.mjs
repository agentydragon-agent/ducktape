import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { prepareLinkedFixture } from "./fixture_preview.mjs";
import { observe } from "./harness.mjs";

function fixture(name, before, init, after = "export {saved};") {
  return prepareLinkedFixture(name, `${before}; var saved = ${init}; ${after}`, {
    entry: "entry.mjs",
    modules: {
      "entry.mjs": after.startsWith("export") ? ["#0", "#2"] : ["#0", "#2", "#3"],
      "owner.mjs": ["#1"],
    },
  });
}

const read = fixture("read", "var marker = 0", "Object.defineProperty");
assertPublicEmissionRefused(read.manifest, read.out);
await withSplitPreview({ manifest: read.manifest }, async ({ directory, entryFile }) => {
  for (const file of [read.sourceFile, entryFile]) {
    assert.equal((await import(pathToFileURL(file))).saved, Object.defineProperty);
  }
  const request = { source: read.sourceFile, spec: read.specFile, directory };
  const model = probeLinkedModel(request);
  assert.equal(model.status, "refused", JSON.stringify(model));
  assert.match(model.reason, /Object/);
  const stable = probeLinkedModel({
    ...request,
    host: { profile: "ecmascript", stableIntrinsicValues: ["Object.defineProperty@1"] },
  });
  assert.equal(stable.status, "refused", JSON.stringify(stable));
  assert.match(stable.reason, /unsupported host contract/);
  assertPublicEmissionRefused(read.manifest, directory);
  assertPublicRecheckRefused(read.manifest, directory);
});

for (const [name, before, expr, check] of [
  ["invoke", "var marker = 0", 'Object.defineProperty({}, "x", {value: 1})', (value) => value.x === 1],
  ["coerce", "var marker = 0", "Object.defineProperty / 2", Number.isNaN],
  ["other-key", "var marker = 0", "Object.getOwnPropertyNames", (value) => value === Object.getOwnPropertyNames],
  [
    "shadow",
    "export const Object = {get defineProperty() {return 1}}",
    "Object.defineProperty",
    (value) => value === 1,
  ],
]) {
  const test = fixture(name, before, expr);
  assertPublicEmissionRefused(test.manifest, test.out);
  assert(check((await import(pathToFileURL(test.sourceFile))).saved), name);
}
// Each observation uses a fresh Node process. Replacing the ambient method
// makes the earlier evaluation capture a different function.
const replaced = fixture(
  "replaced",
  "Object.defineProperty = () => 1",
  "Object.defineProperty",
  "const same = saved === Object.defineProperty; export {same};"
);
assertPublicEmissionRefused(replaced.manifest, replaced.out);
assert.deepEqual(observe(replaced.sourceFile, "same"), { same: true });
await withSplitPreview({ manifest: replaced.manifest, expectedExit: 1 }, ({ directory, entryFile }) => {
  assert.deepEqual(observe(entryFile, "same"), { same: false });
  assertPublicEmissionRefused(replaced.manifest, directory);
  assertPublicRecheckRefused(replaced.manifest, directory);
});
