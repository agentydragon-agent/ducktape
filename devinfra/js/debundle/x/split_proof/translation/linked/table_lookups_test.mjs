import assert from "node:assert/strict";
import { cpSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { parse } from "acorn";
import { generate } from "astring";
import { probeLinkedModel } from "../testing/linked_model_probe.mjs";
import { assertPublicEmissionRefused, assertPublicRecheckRefused } from "../testing/public_refusal.mjs";
import { withSplitPreview } from "../testing/split_preview.mjs";
import { assertMatchedModel, prepareLinkedFixture } from "./fixture_preview.mjs";
import {
  array,
  exportNamed,
  expression,
  id,
  literal,
  member,
  moduleEvaluationOrder,
  program,
  property,
  variable,
} from "./harness.mjs";

const entry = "entry.mjs";
const dataOwner = "data.mjs";
const firstOwner = "first.mjs";
const secondOwner = "second.mjs";
const order = [dataOwner, secondOwner, firstOwner];
const exportNames = ["aliases", "first", "second", "summary"];
const lookup = (key, computed = false) => member(id("table"), id(key), computed);
const set = (left, value) => expression({ type: "AssignmentExpression", operator: "=", left, right: literal(value) });

function fixture(name, width, rows, mutation) {
  const keys = Array.from({ length: width }, (_, i) => `field${i}`);
  const value = (key) => `value-${key}`;
  const last = keys.at(-1);
  const alternate = keys.at(-2);
  const rowKeys = (side, index) => [keys.at(-3 - side - (index % 4)), keys[(index + side) % 4]];
  const makeRows = (side) =>
    array(
      Array.from({ length: rows }, (_, index) => {
        const [tail, head] = rowKeys(side, index);
        return array([
          literal(side),
          literal(index),
          mutation === "key" ? lookup("key", true) : lookup(last),
          array([lookup(tail), array([lookup(head), id("undefined")]), array([])]),
        ]);
      })
    );

  const units = [
    [
      dataOwner,
      variable("const", "table", {
        type: "ObjectExpression",
        properties: keys.map((key) => property(key, literal(value(key)))),
      }),
    ],
    [dataOwner, variable("const", "aliases", array([lookup(keys[0]), lookup(last)]))],
  ];
  if (mutation === "key") units.push([dataOwner, variable("let", "key", literal(last))]);
  // The split evaluates summary and second before first. Both arrays depend on
  // the same provider and capture its field values during initialization.
  units.push(
    [firstOwner, variable("const", "first", makeRows(0))],
    [dataOwner, variable("const", "summary", literal("ready"))],
    [secondOwner, variable("const", "second", makeRows(1))]
  );
  if (mutation === "field") units.push([dataOwner, set(lookup(last), "updated")]);
  if (mutation === "key") units.push([dataOwner, set(id("key"), alternate)]);
  units.push([entry, exportNamed(exportNames.map((name) => [name, name]))]);

  const modules = Object.fromEntries([...order, entry].map((owner) => [owner, []]));
  for (const [index, [owner]] of units.entries()) modules[owner].push(`#${index}`);
  const prepared = prepareLinkedFixture(name, program(units.map(([, node]) => node)), {
    entry,
    modules,
    order,
    sequential: true,
  });

  function expectedRows(side, lookedUp) {
    return Array.from({ length: rows }, (_, index) => {
      const [tail, head] = rowKeys(side, index);
      return [side, index, lookedUp, [value(tail), [value(head), undefined], []]];
    });
  }

  function expected(lookedUp = value(last)) {
    return {
      aliases: [value(keys[0]), value(last)],
      first: expectedRows(0, lookedUp),
      second: expectedRows(1, lookedUp),
      summary: "ready",
    };
  }

  return { ...prepared, expected, last, alternate, alternateValue: value(alternate) };
}

async function expectExports(file, expected) {
  const result = await import(pathToFileURL(file).href);
  assert.deepEqual(Object.keys(result), exportNames);
  for (const name of exportNames) assert.deepEqual(result[name], expected[name], `${file}: ${name}`);
}

{
  const test = fixture("reversed-table", 128, 4);
  const { manifest, out, sourceFile, specFile } = test;
  assertPublicEmissionRefused(manifest, out);
  const expected = test.expected();
  await expectExports(sourceFile, expected);
  await withSplitPreview({ manifest }, async ({ directory, entryFile }) => {
    assert.deepEqual(moduleEvaluationOrder(directory, entry), [...order, entry]);
    await expectExports(entryFile, expected);
    assertMatchedModel(test, directory, [
      [["aliases", "1"], expected.aliases[1]],
      [["first", "0", "2"], expected.first[0][2]],
      [["second", "3", "3", "1", "1"], undefined],
      [["summary"], expected.summary],
    ]);
    assertPublicRecheckRefused(manifest, directory);

    const changedFile = path.join(directory, firstOwner);
    const printed = readFileSync(changedFile, "utf8");
    for (const alteration of ["row-order", "lookup-key"]) {
      const tampered = path.join(path.dirname(directory), alteration);
      cpSync(directory, tampered, { recursive: true });
      const ast = parse(printed, { ecmaVersion: "latest", sourceType: "module" });
      const array = ast.body.find((node) => node.type === "VariableDeclaration").declarations[0].init;
      const changed = test.expected();
      if (alteration === "row-order") {
        array.elements.reverse();
        changed.first.reverse();
      } else {
        const member = array.elements[0].elements[2];
        assert.equal(member.property.name, test.last);
        member.property.name = test.alternate;
        changed.first[0][2] = test.alternateValue;
      }
      writeFileSync(path.join(tampered, firstOwner), generate(ast));
      const model = probeLinkedModel({ source: sourceFile, spec: specFile, directory: tampered });
      assert.equal(model.status, "refused", JSON.stringify(model));
      assert.equal(model.reason_code, "linked_input", JSON.stringify(model));
      assert.match(model.reason, /emitted syntax differs from original unit 2/);
      assertPublicEmissionRefused(manifest, tampered);
      assertPublicRecheckRefused(manifest, tampered);
      await expectExports(path.join(tampered, entry), changed);
    }
  });
}

// The same reversal moves an own-property write or a key-binding write ahead
// of the reads. Both executions finish, but the captured rows are different.
for (const mutation of ["field", "key"]) {
  const test = fixture(`reversed-table-${mutation}`, 128, 3, mutation);
  const { manifest, out, sourceFile, specFile } = test;
  assertPublicEmissionRefused(manifest, out);
  const original = test.expected();
  const changed = test.expected(mutation === "field" ? "updated" : test.alternateValue);
  await expectExports(sourceFile, original);
  await withSplitPreview({ manifest, expectedExit: 1 }, async ({ directory, entryFile }) => {
    assert.deepEqual(moduleEvaluationOrder(directory, entry), [...order, entry]);
    await expectExports(entryFile, changed);
    const model = probeLinkedModel({ source: sourceFile, spec: specFile, directory });
    assert.equal(model.status, "refused", JSON.stringify(model));
    assert.equal(model.reason_code, "probe_mismatch", JSON.stringify(model));
    assert.match(model.reason, /probe executions completed normally with different final states/);
    assert.equal(model.observation.kind, "value", JSON.stringify(model));
    assert.deepEqual(model.observation.path.slice(1), ["0", "2"], JSON.stringify(model));
    assert(["first", "second"].includes(model.observation.path[0]), JSON.stringify(model));
    assert.equal(model.observation.original, JSON.stringify(original.first[0][2]));
    assert.equal(model.observation.split, JSON.stringify(changed.first[0][2]));
  });
}
