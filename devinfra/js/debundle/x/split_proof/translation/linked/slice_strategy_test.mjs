import assert from "node:assert/strict";
import { copyFileSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import {
  assertLinkedPreviewResult,
  assertMatchedModel,
  expectedModelObservations,
  prepareLinkedFixture,
  prepareWorkerFixture,
} from "./fixture_preview.mjs";
import { moduleEvaluationOrder, observe } from "./harness.mjs";

const entry = "entry.mjs";

const orderKept = prepareLinkedFixture(
  "slice-order-kept",
  "const left = []; const other = [99]; export const result = left.length;",
  { entry, modules: { "left.mjs": ["#0"], [entry]: ["#1", "#2"] }, order: ["left.mjs"] }
);
assertPublicEmissionRefused(orderKept.manifest, orderKept.out);
assert.deepEqual(observe(orderKept.sourceFile, "result"), { result: 0 });
await withSplitPreview({ manifest: orderKept.manifest }, ({ directory, entryFile }) => {
  assert.deepEqual(moduleEvaluationOrder(directory, entry), ["left.mjs", entry]);
  assert.deepEqual(observe(entryFile, "result"), { result: 0 });
  assertMatchedModel(orderKept, directory, [[["result"], 0]]);
  assertPublicRecheckRefused(orderKept.manifest, directory);

  const printed = readFileSync(entryFile, "utf8");
  const wrongBinding = printed.replace("left.length", "other.length");
  assert.notEqual(wrongBinding, printed);
  writeFileSync(entryFile, wrongBinding);
  assert.deepEqual(observe(entryFile, "result"), { result: 1 });
  const model = probeLinkedModel({ source: orderKept.sourceFile, spec: orderKept.specFile, directory });
  assert.equal(model.status, "refused", JSON.stringify(model));
  assert.equal(model.reason_code, "linked_input", JSON.stringify(model));
  assert.match(model.reason, /emitted syntax differs from original unit 2/);
  assertPublicEmissionRefused(orderKept.manifest, directory);
  assertPublicRecheckRefused(orderKept.manifest, directory);
});

const omitted = prepareLinkedFixture("omitted-export-unit", "const result = [].length; export { result };", {
  entry,
  modules: { [entry]: ["#0", "#1"] },
});
await assertLinkedPreviewResult(omitted, 0);

const moves = prepareLinkedFixture("slice-moves", "export const left = []; const right = [];", {
  entry,
  modules: { "right.mjs": ["#1"], [entry]: ["#0"] },
  order: ["right.mjs"],
  sequential: true,
});
await withSplitPreview({ manifest: moves.manifest }, ({ directory, entryFile }) => {
  assert.deepEqual(moduleEvaluationOrder(directory, entry), ["right.mjs", entry]);
  for (const file of [moves.sourceFile, entryFile]) assert.deepEqual(observe(file, "left"), { left: [] });
  assertMatchedModel(moves, directory, []);
});

const bindings = prepareLinkedFixture(
  "slice-certified-bindings",
  "let x = 0; let y = 0; x = 1; y = 2; const done = x + y;",
  { entry, modules: { "m0.mjs": ["#1", "#3"], [entry]: ["#0", "#2", "#4"] } }
);
await withSplitPreview({ manifest: bindings.manifest }, ({ directory, entryFile }) => {
  assert.deepEqual(moduleEvaluationOrder(directory, entry), ["m0.mjs", entry]);
  for (const file of [bindings.sourceFile, entryFile]) assert.deepEqual(observe(file, []), {});
  assertMatchedModel(bindings, directory, []);
});

const heritage = prepareLinkedFixture(
  "slice-heritage",
  `
    var Base = class {};
    var Earlier = class extends Base {};
    var Pivot = class extends Base {};
    var config = { factor: 3 };
    var local = [5];
    export var result = config.factor + local[0];
  `,
  { entry, modules: { "prefix.mjs": ["#0", "#1", "#3", "#4"], [entry]: ["#2", "#5"] } }
);
await assertLinkedPreviewResult(heritage, 8);

const providerFallback = prepareLinkedFixture(
  "slice-provider-fallback",
  `import { imported } from "./provider.mjs";
  const result = imported + 1;
  export { result };`,
  { entry, modules: { [entry]: ["#0", "#1", "#2"] } }
);
writeFileSync(providerFallback.providerFile, "export const imported = 41;");
await withSplitPreview({ manifest: providerFallback.manifest }, ({ directory, entryFile }) => {
  copyFileSync(providerFallback.providerFile, path.join(directory, "provider.mjs"));
  for (const file of [providerFallback.sourceFile, entryFile])
    assert.deepEqual(observe(file, "result"), { result: 42 });
  const model = probeLinkedModel({
    source: providerFallback.sourceFile,
    spec: providerFallback.specFile,
    directory,
    providers: ["provider.mjs"],
    observe: [["result"]],
  });
  assert.equal(model.status, "matched", JSON.stringify(model));
  assert(model.fuel > 0);
  assert.deepEqual(model.observed, expectedModelObservations([[["result"], 42]]));
});

const profiled = prepareWorkerFixture(
  "profile-dependent-slice",
  `class Collection { [Symbol.iterator]() { return 42; } }
  export const result = new Collection()[Symbol.iterator]();`
);
assert.deepEqual(observe(profiled.sourceFile, "result"), { result: 42 });
await withSplitPreview({ manifest: profiled.manifest }, ({ directory, entryFile }) => {
  assert.deepEqual(observe(entryFile, "result"), { result: 42 });
  const options = { source: profiled.sourceFile, spec: profiled.specFile, directory, observe: [["result"]] };
  const missing = probeLinkedModel(options);
  assert.equal(missing.status, "refused", JSON.stringify(missing));
  assert.match(missing.reason, /unsupported computed class key/);
  const host = { profile: "browser-page" };
  const model = probeLinkedModel({ ...options, host });
  assert.equal(model.status, "matched", JSON.stringify(model));
  assert(model.fuel > 0);
  assert.deepEqual(model.observed, expectedModelObservations([[["result"], 42]]));
  assert.deepEqual(model.assumptions, [
    "Symbol.iterator returns the well-known iterator symbol without observable effects throughout initialization",
  ]);

  const worker = path.join(directory, "worker.mjs");
  const printed = readFileSync(worker, "utf8");
  const changed = printed.replace(/\[\s*Symbol\.iterator\s*\]/, '["Symbol.iterator"]');
  assert.notEqual(changed, printed);
  writeFileSync(worker, changed);
  assert.deepEqual(observe(entryFile, "result"), { error: "TypeError" });
  const tampered = probeLinkedModel({ ...options, host });
  assert.equal(tampered.status, "refused", JSON.stringify(tampered));
  assert.equal(tampered.reason_code, "linked_input", JSON.stringify(tampered));
  assert.match(tampered.reason, /emitted syntax differs from original unit 0/);
  assertPublicEmissionRefused(profiled.manifest, directory);
  assertPublicRecheckRefused(profiled.manifest, directory);
});
