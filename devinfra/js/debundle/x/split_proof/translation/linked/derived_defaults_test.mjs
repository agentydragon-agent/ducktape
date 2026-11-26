import assert from "node:assert/strict";
import { assertLinkedPreviewResult, prepareLinkedFixture, prepareWorkerFixture } from "./fixture_preview.mjs";
import { assertPublicEmissionRefused } from "../testing/public_refusal.mjs";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { observe } from "./harness.mjs";

const spec = {
  entry: "entry.mjs",
  modules: { "base.mjs": ["#0", "#1"], "entry.mjs": ["#2", "#3"] },
  order: ["base.mjs"],
  sequential: true,
};

async function checkDerived(name, source, expected) {
  const fixture = prepareLinkedFixture(name, source, spec);
  assertPublicEmissionRefused(fixture.manifest, fixture.out);
  await assertLinkedPreviewResult(fixture, expected);
}

await checkDerived(
  "derived-defaults-order",
  `const trace = { value: "" };
    class Base {
      constructor(value) { trace.value += "s"; this.value = value; }
    }
    class Child extends Base {
      ready = trace.value += "f";
      constructor(name, flag = (trace.value += "d", !1), last = flag) {
        const value = name + ":" + flag + ":" + last;
        trace.value += "p";
        super(value);
        trace.value += "b";
      }
    }
    export const result = (() => {
      if (Child.length !== 1) throw "incorrect constructor length";
      const first = new Child("a", undefined, "last");
      if (first.value !== "a:false:last" || first.ready !== "dpsf") throw "incorrect evaluation order";
      if (new Child("b").value !== "b:false:false") throw "missing argument or earlier parameter";
      if (new Child("c", false).value !== "c:false:false") throw "false argument ran the default";
      if (new Child("d", null).value !== "d:null:null") throw "null argument ran the default";
      if (trace.value !== "dpsfbdpsfbpsfbpsfb") throw "incorrect default side effects";
      return first.value;
    })();`,
  "a:false:last"
);

await checkDerived(
  "abrupt-derived-defaults",
  `const trace = { value: "" };
    class Base { constructor() { trace.value += "s"; } }
    class Child extends Base {
      field = trace.value += "f";
      constructor(fail, first = fail ? trace.abort() : typeof later, later = "ready") {
        trace.value += "p";
        super();
        trace.value += "b";
      }
    }
    export const result = (() => {
      trace.abort = () => { trace.value += "d"; throw "default"; };
      try { new Child(false); } catch (error) {
        if (typeof error !== "object") throw error;
        trace.value += "t";
      }
      if (trace.value !== "t") throw "default read a later parameter before initialization";
      try { new Child(true); } catch (error) {
        if (error !== "default") throw error;
        trace.value += "c";
      }
      if (trace.value !== "tdc") throw "an abrupt default reached the constructor body";
      return trace.value;
    })();`,
  "tdc"
);

for (const [name, constructor, reason] of [
  ["receiver-in-default", "constructor(value = this.value) { super(); }", /before super/i],
  [
    "body-shadows-default",
    "constructor(value = outer) { const outer = 2; super(value); }",
    /default parameter|overlap|shadow/i,
  ],
]) {
  const fixture = prepareWorkerFixture(
    name,
    `const outer = 1; class Child extends Object { ${constructor} } export const result = 1;`,
    ["#1", "#2"]
  );
  assertPublicEmissionRefused(fixture.manifest, fixture.out);
  assert.deepEqual(observe(fixture.sourceFile, "result"), { result: 1 });
  await withSplitPreview({ manifest: fixture.manifest }, ({ directory, entryFile }) => {
    const model = probeLinkedModel({ source: fixture.sourceFile, spec: fixture.specFile, directory });
    assert.equal(model.status, "refused", name);
    assert.match(model.reason, reason, name);
    assert.deepEqual(observe(entryFile, "result"), { result: 1 });
  });
}
