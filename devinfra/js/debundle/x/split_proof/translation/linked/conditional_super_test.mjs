import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { caseShard, observe } from "./harness.mjs";
import { assertLinkedPreviewResult, assertMatchedModel, prepareLinkedFixture } from "./fixture_preview.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";

function fixture(name, source, modules, order) {
  return prepareLinkedFixture(name, source, { entry: "entry.mjs", modules, order, sequential: true });
}

const runCase = caseShard();

if (runCase("both-branches")) {
  const split = fixture(
    "conditional-super-both-branches",
    `const trace = { value: "" };
    class Base {
      constructor(first, second) {
        trace.value += "b";
        this.first = first;
        this.second = second;
      }
    }
    class Child extends Base {
      field = trace.value += "f";
      constructor(input) {
        const marker = "x";
        if ((trace.value += "t", input.fast)) super((trace.value += marker, input.value));
        else {
          const local = input.options;
          super(local.value, ...local.extra);
        }
        trace.value += "p";
      }
    }
    export const result = (() => {
      const fast = new Child({ fast: true, value: 3 });
      if (fast.first !== 3 || fast.second !== undefined || fast.field !== "txbf") return false;
      const slow = new Child({ get options() {
        trace.value += "o";
        return { get value() { trace.value += "v"; return 4; }, extra: [5] };
      } });
      return slow.first === 4 && slow.second === 5 && slow.field === "txbfptovbf" &&
        trace.value === "txbfptovbfp";
    })();`,
    { "base.mjs": ["#0", "#1"], "entry.mjs": ["#2", "#3"] },
    ["base.mjs"]
  );
  assertPublicEmissionRefused(split.manifest, split.out);
  assert.deepEqual(observe(split.sourceFile, "result"), { result: true });
  await withSplitPreview({ manifest: split.manifest }, ({ directory, entryFile }) => {
    assert.deepEqual(observe(entryFile, "result"), { result: true });
    assertMatchedModel(split, directory, [[["result"], true]]);
    assertPublicRecheckRefused(split.manifest, directory);
    const printed = readFileSync(entryFile, "utf8");
    assert.match(printed, /super\(local\.value/);
    writeFileSync(entryFile, printed.replace("super(local.value", "super(0"));
    const model = probeLinkedModel({ source: split.sourceFile, spec: split.specFile, directory });
    assert.equal(model.status, "refused");
    assert.equal(model.reason_code, "linked_input");
    assertPublicRecheckRefused(split.manifest, directory);
    assert.deepEqual(observe(entryFile, "result"), { result: false });
  });
}

if (runCase("throwing-argument")) {
  const split = fixture(
    "conditional-super-throwing-argument",
    `const trace = { value: "" };
    class Base { constructor() { trace.value += "b"; } }
    class Child extends Base {
      field = trace.value += "f";
      constructor(fast, input) {
        if (fast) super();
        else {
          const local = input;
          super(local.fail);
        }
        trace.value += "p";
      }
    }
    export const result = (() => {
      try { new Child(false, { get fail() { trace.value += "x"; throw 3; } }); }
      catch (error) { if (error !== 3) throw error; }
      return trace.value;
    })();`,
    { "base.mjs": ["#0", "#1"], "entry.mjs": ["#2", "#3"] },
    ["base.mjs"]
  );
  assertPublicEmissionRefused(split.manifest, split.out);
  await assertLinkedPreviewResult(split, "x");
}

if (runCase("missing-branch")) {
  const split = fixture(
    "conditional-super-missing-branch",
    `class Base {}
    class Child extends Base { constructor(run) { if (run) super(); } }
    export const result = new Child(false);`,
    { "base.mjs": ["#0"], "entry.mjs": ["#1", "#2"] },
    ["base.mjs"]
  );
  assertPublicEmissionRefused(split.manifest, split.out);
  assert.deepEqual(observe(split.sourceFile, "result"), { error: "ReferenceError" });
  await withSplitPreview({ manifest: split.manifest }, ({ directory, entryFile }) => {
    const model = probeLinkedModel({ source: split.sourceFile, spec: split.specFile, directory });
    assert.equal(model.status, "refused");
    assert.match(model.reason, /expected a direct super call/);
    assert.deepEqual(observe(entryFile, "result"), { error: "ReferenceError" });
  });
}
