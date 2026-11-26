import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { assertMatchedModel, prepareLinkedFixture } from "./fixture_preview.mjs";
import {
  id,
  literal,
  call,
  returns,
  block,
  tryStatement,
  catchClause,
  arrow,
  variable,
  property,
  exportNamed,
  program,
  observe,
  moduleEvaluationOrder,
} from "./harness.mjs";

// Source initializes left, then right. Pin the reverse order across all cases.
// Mutating one initializer to read its neighbor introduces a TDZ in exactly one execution.
for (const [changed, first, second] of [
  ["left", "low", "high"],
  ["right", 42, 0],
]) {
  const spec = {
    entry: "entry.mjs",
    modules: { "left.mjs": ["#0"], "right.mjs": ["#1"], "entry.mjs": ["#2", "#3"] },
    order: ["right.mjs", "left.mjs"],
    sequential: true,
  };
  for (const dependent of [false, true]) {
    const readsRight = dependent && changed === "left";
    const readsLeft = dependent && changed === "right";
    const source = program([
      variable("const", "left", readsRight ? id("right") : literal(first)),
      variable("const", "right", readsLeft ? id("left") : literal(second)),
      variable("const", "pair", {
        type: "ObjectExpression",
        properties: [property("first", id("left")), property("second", id("right"))],
      }),
      exportNamed([["pair", "result"]]),
    ]);
    const fixture = prepareLinkedFixture(`reordered-providers-${changed}-${dependent}`, source, spec);
    const { manifest, out, sourceFile, specFile } = fixture;
    assertPublicEmissionRefused(manifest, out);
    const tdz = { error: "ReferenceError" };
    const normal = { result: { first: readsRight ? second : first, second: readsLeft ? first : second } };
    assert.deepEqual(observe(sourceFile, "result"), readsRight ? tdz : normal);
    await withSplitPreview({ manifest, expectedExit: dependent ? 1 : 0 }, ({ directory, entryFile }) => {
      assert.deepEqual(moduleEvaluationOrder(directory, spec.entry), [...spec.order, spec.entry]);
      assert.deepEqual(observe(entryFile, "result"), readsLeft ? tdz : normal);
      if (dependent) {
        const model = probeLinkedModel({ source: sourceFile, spec: specFile, directory });
        assert.equal(model.status, "refused", JSON.stringify(model));
        assert.equal(model.reason_code, "probe_throw", JSON.stringify(model));
        assert.equal(model.reason, `${readsRight ? "original" : "split"} threw during linked initialization`);
      } else {
        assertMatchedModel(fixture, directory, [
          [["result", "first"], first],
          [["result", "second"], second],
        ]);
      }
    });
  }
}

// Both calls can complete even when the formatter observes their order: catch
// the TDZ and return the usual formatted value until the captured call finishes.
for (const [observed, leftArg, rightArg] of [
  ["left", "sun", "rain"],
  ["right", 13, false],
]) {
  const format = {
    type: "TemplateLiteral",
    expressions: [id("prefix"), id("value")],
    quasis: ["", ":", ""].map((text, index) => ({
      type: "TemplateElement",
      value: { raw: text, cooked: text },
      tail: index === 2,
    })),
  };
  const left = `label:${leftArg}`;
  const right = `label:${rightArg}`;
  const original = { left, right };
  const shared = observed === "left" ? left : right;
  const dependentSource = observed === "left" ? { left, right: shared } : original;
  const dependentReversed = observed === "right" ? { left: shared, right } : original;
  assert.notDeepEqual(dependentSource, dependentReversed);

  for (const [variant, capturesCall, reversed] of [
    ["independent", false, true],
    ["same-order", true, false],
    ["order-sensitive", true, true],
  ]) {
    const body = capturesCall
      ? block([tryStatement(block([returns(id(observed))]), catchClause(null, block([returns(format)])))])
      : format;
    const source = program([
      variable("const", "prefix", literal("label")),
      variable("const", "format", arrow([id("value")], body)),
      variable("const", "left", call(id("format"), [literal(leftArg)])),
      variable("const", "right", call(id("format"), [literal(rightArg)])),
      variable("const", "pair", {
        type: "ObjectExpression",
        properties: [property("left", id("left")), property("right", id("right"))],
      }),
      exportNamed([["pair", "result"]]),
    ]);
    const calls = reversed ? ["right.mjs", "left.mjs"] : ["left.mjs", "right.mjs"];
    const spec = {
      entry: "entry.mjs",
      modules: { "format.mjs": ["#0", "#1"], "left.mjs": ["#2"], "right.mjs": ["#3"], "entry.mjs": ["#4", "#5"] },
      order: ["format.mjs", ...calls],
      sequential: true,
    };
    const fixture = prepareLinkedFixture(`reordered-formatter-${observed}-${variant}`, source, spec);
    const { manifest, out, sourceFile, specFile } = fixture;
    const bundled = capturesCall ? dependentSource : original;
    const differs = capturesCall && reversed;
    const expected = differs ? dependentReversed : bundled;
    assertPublicEmissionRefused(manifest, out);
    assert.deepEqual(observe(sourceFile, "result"), { result: bundled });
    await withSplitPreview({ manifest, expectedExit: differs ? 1 : 0 }, ({ directory, entryFile }) => {
      assert.deepEqual(moduleEvaluationOrder(directory, spec.entry), [...spec.order, spec.entry]);
      assert.deepEqual(observe(entryFile, "result"), { result: expected });
      if (differs) {
        const model = probeLinkedModel({ source: sourceFile, spec: specFile, directory });
        assert.equal(model.status, "refused", JSON.stringify(model));
        assert.equal(model.reason_code, "probe_mismatch", JSON.stringify(model));
        const changed = observed === "left" ? "right" : "left";
        assert.deepEqual(model.observation, {
          kind: "value",
          path: ["result", changed],
          original: JSON.stringify(bundled[changed]),
          split: JSON.stringify(expected[changed]),
        });
      } else {
        assertMatchedModel(fixture, directory, [
          [["result", "left"], expected.left],
          [["result", "right"], expected.right],
        ]);
      }
    });
  }
}

// These distinct world calls both return undefined in World.probe, so the concrete
// final states match. Other worlds can distinguish the order of these calls.
// The public command refuses the reversed schedule. Node can distinguish it using a recording host method.
{
  const localeCompare = (left, right) =>
    call(
      {
        type: "MemberExpression",
        object: literal(left),
        property: id("localeCompare"),
        computed: false,
        optional: false,
      },
      [literal(right)]
    );
  const source = program([
    variable("const", "first", localeCompare("x", "y")),
    variable("const", "second", localeCompare("z", "w")),
    exportNamed([
      ["first", "first"],
      ["second", "second"],
    ]),
  ]);
  const spec = {
    entry: "entry.mjs",
    modules: { "left.mjs": ["#0"], "right.mjs": ["#1"], "entry.mjs": ["#2"] },
    order: ["right.mjs", "left.mjs"],
    sequential: true,
  };
  const fixture = prepareLinkedFixture("reordered-probe-equivalent-host-calls", source, spec);
  const { manifest, out, sourceFile } = fixture;
  assertPublicEmissionRefused(manifest, out);
  await withSplitPreview({ manifest, expectedExit: 1 }, async ({ directory, entryFile }) => {
    assert.deepEqual(moduleEvaluationOrder(directory, spec.entry), [...spec.order, spec.entry]);
    assertMatchedModel(fixture, directory, [
      [["first"], undefined],
      [["second"], undefined],
    ]);

    const original = String.prototype.localeCompare;
    const log = [];
    String.prototype.localeCompare = function (argument) {
      log.push([String(this), argument]);
      return 0;
    };
    try {
      const bundle = await import(pathToFileURL(sourceFile).href);
      const preview = await import(pathToFileURL(entryFile).href);
      assert.deepEqual([bundle.first, bundle.second, preview.first, preview.second], [0, 0, 0, 0]);
    } finally {
      String.prototype.localeCompare = original;
    }
    assert.deepEqual(log, [
      ["x", "y"],
      ["z", "w"],
      ["z", "w"],
      ["x", "y"],
    ]);
    assertPublicEmissionRefused(manifest, directory);
    assertPublicRecheckRefused(manifest, directory);
  });
}
