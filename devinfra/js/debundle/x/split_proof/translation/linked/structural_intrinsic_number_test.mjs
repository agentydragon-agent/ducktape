import assert from "node:assert/strict";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { prepareLinkedFixture } from "./fixture_preview.mjs";
import { observe } from "./harness.mjs";

function fixture(name, before, operand) {
  return prepareLinkedFixture(name, `${before}; var result = ${operand} / 12; export { result };`, {
    entry: "entry.mjs",
    modules: { "entry.mjs": ["#0", "#2"], "angle.mjs": ["#1"] },
  });
}

for (const [name, before, operand, expected, moved, expectedExit] of [
  ["ordinary", "var marker = 1", "Math.PI", Math.PI / 12, Math.PI / 12, 0],
  ["replaced", "globalThis.Math = { PI: 24 }", "Math.PI", 2, Math.PI / 12, 1],
  ["getter", "globalThis.Math = { get PI() { return 36; } }", "Math.PI", 3, Math.PI / 12, 1],
  ["coercion", "Object.prototype.valueOf = () => 48", "({})", 4, null, 1],
]) {
  const { manifest, out, sourceFile, specFile } = fixture(name, before, operand);
  assertPublicEmissionRefused(manifest, out);
  assert.deepEqual(observe(sourceFile, "result"), { result: expected });
  await withSplitPreview({ manifest, expectedExit }, ({ directory, entryFile }) => {
    assert.deepEqual(observe(entryFile, "result"), { result: moved });
    if (name === "ordinary") {
      const request = { source: sourceFile, spec: specFile, directory };
      const model = probeLinkedModel({ ...request, host: { profile: "browser-page" } });
      assert.equal(model.status, "refused", JSON.stringify(model));
      assert.match(model.reason, /Math\.PI/);
      const stable = probeLinkedModel({
        ...request,
        host: { profile: "browser-page", stableIntrinsicValues: ["Math.PI@1"] },
      });
      assert.equal(stable.status, "refused", JSON.stringify(stable));
      assert.match(stable.reason, /unsupported host contract/);
    }
    assertPublicEmissionRefused(manifest, directory);
    assertPublicRecheckRefused(manifest, directory);
  });
}

const shadow = fixture("lexical", "export const Math = { get PI() { return 24; } }", "Math.PI");
assertPublicEmissionRefused(shadow.manifest, shadow.out);
assert.deepEqual(observe(shadow.sourceFile, "result"), { result: 2 });
