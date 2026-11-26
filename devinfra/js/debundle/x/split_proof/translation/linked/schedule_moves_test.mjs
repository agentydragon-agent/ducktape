import assert from "node:assert/strict";
import { copyFileSync, cpSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { parse } from "acorn";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { assertMatchedModel, expectedModelObservations, prepareLinkedFixture } from "./fixture_preview.mjs";
import { observe } from "./harness.mjs";

function fixture(name, source, moved, kept, provider = "") {
  const prepared = prepareLinkedFixture(name, source, {
    entry: "entry.mjs",
    modules: { "entry.mjs": kept, "scroll.mjs": moved },
  });
  if (provider) writeFileSync(prepared.providerFile, provider);
  return prepared;
}

async function checkPreview(fixture, expectedExit, check) {
  await withSplitPreview({ manifest: fixture.manifest, expectedExit }, check);
}

function request(fixture, directory) {
  return { source: fixture.sourceFile, spec: fixture.specFile, directory };
}

function assertChange(fixture, directory, exportName, original, split) {
  const paths = [[exportName]];
  const model = probeLinkedModel({ ...request(fixture, directory), observe: paths, mismatchFuel: 128 });
  assert.equal(model.status, "refused", JSON.stringify(model));
  assert.equal(model.reason_code, "probe_mismatch", JSON.stringify(model));
  const [before] = expectedModelObservations([[paths[0], original]]);
  const [after] = expectedModelObservations([[paths[0], split]]);
  assert.deepEqual(model.observed, [{ path: paths[0], original: before.original, split: after.split }]);
}

// Creating the class stores the initializer; only construction reads `later`.
const instanceField = fixture(
  "move-class-with-instance-field",
  `const before = 3;
   const C = class { value = later(); };
   function later() { return 7; }
   export { before, C, later };`,
  ["#1"],
  ["#0", "#2", "#3"]
);
assertPublicEmissionRefused(instanceField.manifest, instanceField.out);
await checkPreview(instanceField, 0, async ({ directory, entryFile }) => {
  for (const file of [instanceField.sourceFile, entryFile]) {
    const { before, C } = await import(pathToFileURL(file).href);
    assert.equal(before, 3);
    assert.equal(new C().value, 7);
  }
  assertMatchedModel(instanceField, directory, [[["before"], 3]]);
  assertPublicRecheckRefused(instanceField.manifest, directory);
});

const staticField = fixture(
  "move-class-with-static-field",
  `const before = 3;
   const C = class { static value = { answer: 7 }; static owner = this; };
   export { before, C };`,
  ["#1"],
  ["#0", "#2"]
);
await checkPreview(staticField, 0, async ({ directory, entryFile }) => {
  for (const file of [staticField.sourceFile, entryFile]) {
    const { before, C } = await import(pathToFileURL(file).href);
    assert.equal(before, 3);
    assert.equal(C.value.answer, 7);
    assert.equal(C.owner, C);
  }
  assertMatchedModel(staticField, directory, [
    [["before"], 3],
    [["C", "value", "answer"], 7],
  ]);
});

const eagerField = fixture(
  "class-static-field-must-not-cross-binding",
  `const before = 3;
   const C = class { static value = before; };
   export { before, C };`,
  ["#1"],
  ["#0", "#2"]
);
await checkPreview(eagerField, 1, async ({ directory, entryFile }) => {
  assert.equal((await import(pathToFileURL(eagerField.sourceFile).href)).C.value, 3);
  await assert.rejects(import(pathToFileURL(entryFile).href), ReferenceError);
  const model = probeLinkedModel(request(eagerField, directory));
  assert.equal(model.status, "refused", JSON.stringify(model));
  assert.equal(model.reason_code, "probe_throw", JSON.stringify(model));
  assert.match(model.reason, /split threw during linked initialization/);
});

const opaqueContext = fixture(
  "retained-dynamic-import-needs-module-context",
  `const load = () => import("./lazy.mjs");
   const phase = 1;
   export { load, phase };`,
  ["#1"],
  ["#0", "#2"]
);
const lazySource = "export const location = import.meta.url;";
const originalLazy = path.join(path.dirname(opaqueContext.sourceFile), "lazy.mjs");
writeFileSync(originalLazy, lazySource);
await checkPreview(opaqueContext, 0, async ({ directory, entryFile }) => {
  const model = probeLinkedModel(request(opaqueContext, directory));
  assert.equal(model.status, "refused", JSON.stringify(model));
  assert.match(model.reason, /[Ii]mport|source-module/);
  const previewLazy = path.join(directory, "lazy.mjs");
  writeFileSync(previewLazy, lazySource);
  for (const [file, lazy] of [
    [opaqueContext.sourceFile, originalLazy],
    [entryFile, previewLazy],
  ]) {
    const { load, phase } = await import(pathToFileURL(file).href);
    assert.equal(phase, 1);
    assert.equal((await load()).location, pathToFileURL(lazy).href);
  }
});

const typedArraySource = `import { seed } from "./provider.mjs";
   const bytes = new Uint8Array([seed, 17]);
   const read = (position) => bytes[position];
   var scroll = ({ amount }) => amount + 1;
   const answer = read(1);
   export { scroll as Bg, bytes, answer };`;

const safe = fixture(
  "move-across-typed-array",
  typedArraySource,
  ["#3"],
  ["#0", "#1", "#2", "#4", "#5"],
  "export const seed = 9;"
);

const multipleMoves = fixture(
  "multiple-moves",
  typedArraySource,
  ["#2", "#3"],
  ["#0", "#1", "#4", "#5"],
  "export const seed = 9;"
);
for (const move of [safe, multipleMoves]) {
  await checkPreview(move, 1, async ({ directory, entryFile }) => {
    copyFileSync(move.providerFile, path.join(directory, "provider.mjs"));
    for (const file of [move.sourceFile, entryFile]) {
      const namespace = await import(pathToFileURL(file).href);
      assert.deepEqual(Object.keys(namespace), ["Bg", "answer", "bytes"]);
      assert.equal(namespace.answer, 17);
      assert.equal(namespace.Bg({ amount: 22 }), 23);
      assert(namespace.bytes instanceof Uint8Array);
      assert.deepEqual([...namespace.bytes], [9, 17]);
    }
    if (move !== safe) return;
    const worker = path.join(directory, "scroll.mjs");
    const printed = readFileSync(worker, "utf8");
    const changed = printed.replace("amount + 1", "amount + 2");
    assert.notEqual(changed, printed);
    writeFileSync(worker, changed);
    const model = probeLinkedModel({
      ...request(move, directory),
      providers: ["provider.mjs"],
      host: { profile: "browser-page" },
    });
    assert.equal(model.status, "refused", JSON.stringify(model));
    assert.equal(model.reason_code, "linked_input", JSON.stringify(model));
    assert.match(model.reason, /emitted syntax differs from original unit 3/);
    assertPublicEmissionRefused(move.manifest, directory);
    assertPublicRecheckRefused(move.manifest, directory);
    const tampered = path.join(path.dirname(directory), "tampered");
    cpSync(directory, tampered, { recursive: true });
    const { Bg } = await import(pathToFileURL(path.join(tampered, "entry.mjs")).href);
    assert.equal(Bg({ amount: 22 }), 24);
  });
}

const laterCapture = fixture(
  "previously-moved-closure-captures-next-region",
  `const first = 1;
   var observe = () => later;
   const result = observe() + first;
   var later = 7;
   export { observe, result, later };`,
  ["#1", "#3"],
  ["#0", "#2", "#4"]
);
await checkPreview(laterCapture, 1, ({ directory, entryFile }) => {
  assert.deepEqual(observe(laterCapture.sourceFile, "result"), { result: null }); // JSON view of NaN
  assert.deepEqual(observe(entryFile, "result"), { result: 8 });
  assertChange(laterCapture, directory, "result", NaN, 8);
});

const deferredPair = fixture(
  "adjacent-closure-and-captured-initializer",
  `const bytes = new Uint8Array([17]);
   var inspect = value => read(value);
   var read = value => value + 1;
   export { bytes, inspect, read };`,
  ["#1", "#2"],
  ["#0", "#3"]
);
await checkPreview(deferredPair, 0, async ({ directory, entryFile }) => {
  for (const file of [deferredPair.sourceFile, entryFile]) {
    const { bytes, inspect } = await import(pathToFileURL(file).href);
    assert.equal(inspect(bytes[0]), 18);
  }
});

// The helper and its two interleaved declarations are assigned together.
const interleaved = fixture(
  "ordered-forward-capture",
  `const bytes = new Uint8Array([7]);
   var inspect = x => read(x);
   var offset = () => 2;
   var scale = x => offset() * x;
   var read = x => x + 1;
   export { bytes, inspect, offset, scale, read };`,
  ["#1", "#2", "#3", "#4"],
  ["#0", "#5"]
);
await checkPreview(interleaved, 0, async ({ directory, entryFile }) => {
  const emittedGroup = parse(readFileSync(path.join(directory, "scroll.mjs"), "utf8"), {
    sourceType: "module",
    ecmaVersion: "latest",
  });
  assert.deepEqual(
    emittedGroup.body.flatMap((node) => (node.declaration ?? node).declarations?.map((d) => d.id.name) ?? []),
    ["inspect", "offset", "scale", "read"]
  );
  for (const file of [interleaved.sourceFile, entryFile]) {
    const { bytes, inspect, scale } = await import(pathToFileURL(file).href);
    assert.equal(inspect(scale(bytes[0])), 15);
  }
});

// An actual read by a hoisted function during the crossing is observable,
// whether entered directly or by property access. Neither permits the group.
for (const access of ["peek()", "receiver.value"]) {
  const active = fixture(
    access === "peek()" ? "group-crosses-call" : "group-crosses-getter",
    `function peek() { return typeof read; }
     const receiver = { get value() { return peek(); } };
     const before = ${access};
     var inspect = () => read();
     var independent = () => 3;
     var read = () => 7;
     export { before, inspect, independent, read };`,
    ["#3", "#4", "#5"],
    ["#0", "#1", "#2", "#6"]
  );
  await checkPreview(active, 1, ({ directory, entryFile }) => {
    assert.deepEqual(observe(active.sourceFile, "before"), { before: "undefined" });
    assert.deepEqual(observe(entryFile, "before"), { before: "function" });
    assertChange(active, directory, "before", "undefined", "function");
  });
}

const reentry = fixture(
  "getter-observes-captured-initializer",
  `function peek() { return typeof read; }
   const receiver = { get value() { return peek(); } };
   const before = receiver.value;
   var inspect = () => read();
   var read = () => 7;
   export { before, inspect, read };`,
  ["#3", "#4"],
  ["#0", "#1", "#2", "#5"]
);
await checkPreview(reentry, 1, ({ directory, entryFile }) => {
  assert.deepEqual(observe(reentry.sourceFile, "before"), { before: "undefined" });
  assert.deepEqual(observe(entryFile, "before"), { before: "function" });
  assertChange(reentry, directory, "before", "undefined", "function");
});

// The same retained closure is harmless to the first pivot but can read the
// second. Its linked capture stays fixed; the region to exclude changes.
const retainedReader = `var observe = () => later;
   const before = observe();
   var independent = 1;
   var later = 2;
   export { before, independent, later };`;
const one = fixture("retained-capture-one-pivot", retainedReader, ["#2"], ["#0", "#1", "#3", "#4"]);
await checkPreview(one, 0, async ({ directory, entryFile }) => {
  for (const file of [one.sourceFile, entryFile]) {
    const values = await import(pathToFileURL(file).href);
    assert.equal(values.before, undefined);
    assert.equal(values.later, 2);
  }
  assertMatchedModel(one, directory, [
    [["before"], undefined],
    [["later"], 2],
  ]);
});
const two = fixture("retained-capture-two-pivots", retainedReader, ["#2", "#3"], ["#0", "#1", "#4"]);
await checkPreview(two, 1, ({ directory, entryFile }) => {
  assert.deepEqual(observe(two.sourceFile, "before"), { before: undefined });
  assert.deepEqual(observe(entryFile, "before"), { before: 2 });
  assertChange(two, directory, "before", undefined, 2);
});
