import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { prepareLinkedFixture } from "./fixture_preview.mjs";

function fixture(name, crossed, init = "new WeakMap()") {
  return prepareLinkedFixture(name, `${crossed}; var cache = ${init}; export {cache};`, {
    entry: "entry.mjs",
    modules: { "entry.mjs": ["#0", "#2"], "owner.mjs": ["#1"] },
  });
}

const neutral = fixture("neutral", "var phase = 1");
assertPublicEmissionRefused(neutral.manifest, neutral.out);
await withSplitPreview({ manifest: neutral.manifest }, async ({ directory, entryFile }) => {
  for (const file of [neutral.sourceFile, entryFile]) {
    const { cache } = await import(pathToFileURL(file).href);
    assert.equal(WeakMap.prototype.has.call(cache, {}), false);
  }
  const model = probeLinkedModel({
    source: neutral.sourceFile,
    spec: neutral.specFile,
    directory,
    host: { profile: "browser-page" },
  });
  assert.equal(model.status, "refused", JSON.stringify(model));
  assert.equal(model.reason_code, "probe_unknown", JSON.stringify(model));
  assert.match(model.reason, /host value window\.WeakMap is constructed/);
  assertPublicEmissionRefused(neutral.manifest, directory);
  assertPublicRecheckRefused(neutral.manifest, directory);
});

// No property or prototype tag encodes [[WeakMapData]]. The inherited brand
// string and instanceof both accept this ordinary fake. A native method does not.
const native = new WeakMap();
const other = new WeakMap();
const key = {};
const fake = Object.create(WeakMap.prototype);
assert.notEqual(native, other);
assert.equal(Object.getPrototypeOf(native), Object.getPrototypeOf(fake));
assert.deepEqual(Reflect.ownKeys(native), Reflect.ownKeys(fake));
assert(fake instanceof WeakMap);
assert.equal(Object.prototype.toString.call(native), Object.prototype.toString.call(fake));
Object.setPrototypeOf(native, null);
Object.setPrototypeOf(fake, null);
const { set, get, has } = WeakMap.prototype;
assert.equal(has.call(native, key), false);
assert.throws(() => has.call(fake, key), TypeError);
assert.equal(set.call(native, key, 7), native);
assert.equal(get.call(native, key), 7);
assert.equal(has.call(other, key), false);

// Inspect the original and the *uncertified* reordered preview in separate
// processes. The same stable replacement can return a shared object or reenter.
const observe = (file, mode) => {
  const probe = `
    const [file, mode] = process.argv.slice(1);
    const Native = WeakMap;
    globalThis.phase = 0;
    globalThis.sentinel = {};
    const log = [];
    if (mode === "getter") Object.defineProperty(globalThis, "WeakMap", {
      get() { log.push(phase); return Native; }, configurable: true
    });
    if (mode === "reentry") globalThis.WeakMap = class extends Native {
      constructor() { super(); log.push(phase); }
    };
    const { cache } = await import(file);
    const shared = cache === sentinel;
    console.log(JSON.stringify({ log, shared }));
  `;
  const run = spawnSync(process.execPath, ["--input-type=module", "-e", probe, pathToFileURL(file).href, mode], {
    encoding: "utf8",
  });
  assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
};
const marker = fixture("phase", "globalThis.phase = 1");
assertPublicEmissionRefused(marker.manifest, marker.out);
await withSplitPreview({ manifest: marker.manifest }, ({ entryFile }) => {
  for (const mode of ["getter", "reentry"]) {
    assert.deepEqual(observe(marker.sourceFile, mode), { log: [1], shared: false });
    assert.deepEqual(observe(entryFile, mode), { log: [0], shared: false });
  }
});

const sentinelCtor = "class { constructor() { return globalThis.sentinel; } }";
for (const [name, crossed] of [
  ["replaced", "globalThis.WeakMap = " + sentinelCtor],
  ["shadowed", "export const WeakMap = " + sentinelCtor],
]) {
  const test = fixture(name, crossed);
  assertPublicEmissionRefused(test.manifest, test.out);
  assert.deepEqual(observe(test.sourceFile, name), { log: [], shared: true });
  if (name === "replaced") {
    await withSplitPreview({ manifest: test.manifest, expectedExit: 1 }, ({ entryFile }) => {
      assert.deepEqual(observe(entryFile, name), { log: [], shared: false });
    });
  }
}
