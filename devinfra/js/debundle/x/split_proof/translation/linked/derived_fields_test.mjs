import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { assertLinkedPreviewResult, assertMatchedModel, prepareLinkedFixture } from "./fixture_preview.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { observe } from "./harness.mjs";

function fixture(name, source, modules = { "worker.mjs": ["#0"], "entry.mjs": ["#1", "#2"] }, order = ["worker.mjs"]) {
  return prepareLinkedFixture(name, source, { entry: "entry.mjs", modules, order, sequential: true });
}

const implicit = fixture(
  "default-derived-fields",
  `class Base {
    constructor(id) { this.id = id; }
    set items(value) { throw "inherited setter"; }
  }
  class Child extends Base {
    items = [];
    alias = this.items;
    idAtSuper = this.id;
  }
  export const result = (() => {
    const a = new Child(3), b = new Child(4);
    if (a.items === b.items || a.items !== a.alias || b.items !== b.alias) throw "instance fields";
    if (a.idAtSuper !== 3 || b.idAtSuper !== 4) throw "super arguments";
    return a.items.length;
  })();`
);
assertPublicEmissionRefused(implicit.manifest, implicit.out);
assert.deepEqual(observe(implicit.sourceFile, "result"), { result: 0 });
await withSplitPreview({ manifest: implicit.manifest }, ({ directory, entryFile }) => {
  assert.deepEqual(observe(entryFile, "result"), { result: 0 });
  assertMatchedModel(implicit, directory, [[["result"], 0]]);
  assertPublicRecheckRefused(implicit.manifest, directory);
  const original = readFileSync(entryFile, "utf8");
  const changed = original.replace(/items\s*=\s*\[\s*\]/, "items = [1]");
  assert.notEqual(changed, original);
  writeFileSync(entryFile, changed);
  assert.deepEqual(observe(entryFile, "result"), { result: 1 });
  const model = probeLinkedModel({ source: implicit.sourceFile, spec: implicit.specFile, directory });
  assert.equal(model.status, "refused");
  assert.equal(model.reason_code, "linked_input");
  assertPublicRecheckRefused(implicit.manifest, directory);
});

const explicit = fixture(
  "explicit-derived-fields",
  `const label = "outer";
  class Base { constructor() { return { phase: "base" }; } }
  class Child extends Base {
    seen = this.phase;
    origin = label;
    constructor(label) {
      super();
      if (this.seen !== "base" || this.origin !== "outer") throw "field initialization";
      this.phase = label;
    }
  }
  export const result = (new Child("body")).phase;`,
  { "base.mjs": ["#0", "#1"], "entry.mjs": ["#2", "#3"] },
  ["base.mjs"]
);
assertPublicEmissionRefused(explicit.manifest, explicit.out);
await assertLinkedPreviewResult(explicit, "body");

const abrupt = fixture(
  "abrupt-derived-fields",
  `const trace = { count: 0 };
  class Base { constructor(fail) { if (fail) throw "parent"; } }
  class Child extends Base {
    before = ++trace.count;
    failure = (() => { throw "field"; })();
    after = ++trace.count;
    constructor(fail) { super(fail); ++trace.count; }
  }
  export const result = (() => {
    try { new Child(true); } catch (error) { if (error !== "parent") throw error; }
    if (trace.count !== 0) throw "after failed parent";
    try { new Child(false); } catch (error) { if (error !== "field") throw error; }
    return trace.count;
  })();`,
  { "base.mjs": ["#0", "#1"], "entry.mjs": ["#2", "#3"] },
  ["base.mjs"]
);
assertPublicEmissionRefused(abrupt.manifest, abrupt.out);
await assertLinkedPreviewResult(abrupt, 1);

const forwarded = fixture(
  "derived-fresh-arguments",
  `const identity = {};
  class Base {
    constructor(first, second, third) {
      this.values = [first === identity, second === undefined ? "empty" : second, third === undefined];
    }
  }
  class Child extends Base {
    constructor() { (super(...arguments), this.finished = true); }
  }
  class Further extends Child {}
  export const result = (() => {
    const empty = new Further(), full = new Further(identity, 8);
    if (!empty.finished || !full.finished || Child.length !== 0) throw "constructor";
    return [empty.values, full.values];
  })();`,
  { "base.mjs": ["#0", "#1"], "entry.mjs": ["#2", "#3", "#4"] },
  ["base.mjs"]
);
assertPublicEmissionRefused(forwarded.manifest, forwarded.out);
await assertLinkedPreviewResult(
  forwarded,
  [
    [false, "empty", true],
    [true, 8, true],
  ],
  [
    [["result", "0", "0"], false],
    [["result", "0", "1"], "empty"],
    [["result", "0", "2"], true],
    [["result", "1", "0"], true],
    [["result", "1", "1"], 8],
    [["result", "1", "2"], true],
  ]
);
