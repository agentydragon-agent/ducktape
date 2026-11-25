import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { gunzipSync } from "node:zlib";
import { acorn, eslintScope } from "../../translation/parser.mjs";
import { parseModule, topLevelStatements } from "../../translation/scope_metadata.mjs";
import { assertSelectedSourceUnits } from "../../translation/testing/ast_assertions.mjs";
import { split } from "../../translation/testing/split.mjs";

const chunks = process.env.EXCALIDRAW_INPUTS.split(" ").find((file) => file.endsWith("/chunks"));
assert(chunks);
const tally = { certified: 0, refused: 0 };
for (const [chunk, spec] of [
  ["editor", process.env.EDITOR_LEAN_SPEC],
  ["main", process.env.MAIN_LEAN_SPEC],
]) {
  const dir = path.join(process.env.TEST_UNDECLARED_OUTPUTS_DIR, chunk);
  mkdirSync(dir, { recursive: true });
  const reports = path.join(process.env.SPEC_GRAPHS, "reports/tree", chunk);
  const graph = JSON.parse(gunzipSync(readFileSync(path.join(reports, "dependency_graph.json.gz"))));
  assert.equal(graph.chunk_id, chunk);
  const validation = JSON.parse(readFileSync(path.join(reports, "translation_validation.json"), "utf8"));
  assert(validation.gate_accepts && validation.accepts);
  const sourceFile = path.join(chunks, chunk + ".js");
  const source = readFileSync(sourceFile, "utf8");
  const parsed = parseModule(source, acorn.parse, eslintScope);
  const units = topLevelStatements(parsed.ast);
  const nodes = graph.nodes.sort((a, b) => a.statement_ordinal - b.statement_ordinal);
  assert.equal(nodes.length, units.length);
  const entry = "entry.mjs";
  const owners = new Map(graph.module_graph.nodes.map((m) => [m.key, m.kind === "entry" ? entry : m.path + ".mjs"]));
  for (const [i, node] of nodes.entries()) {
    assert.equal(node.statement_ordinal, i);
    const ast = units[i].node;
    const binding = ast.declarations?.[0]?.id ?? ast.id;
    if (binding?.type === "Identifier")
      assert(
        node.declared_bindings.some((b) => b.binding === binding.name),
        chunk + " unit " + i
      );
  }
  // The placement census covers the statements in the Rust emitted schedule.
  const effects = JSON.parse(readFileSync(path.join(reports, "effect_translation_validation.json"), "utf8"));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const schedule = effects.emitted_order.map((id) => byId.get("unit:" + id).statement_ordinal);
  assert.equal(schedule.length, units.length);
  assert.deepEqual(
    schedule.toSorted((a, b) => a - b),
    nodes.map((node) => node.statement_ordinal)
  );
  const write = (name, value) => {
    const file = path.join(dir, name + ".json");
    writeFileSync(file, JSON.stringify(value));
    return file;
  };
  const rendered = path.join(process.env.TEST_TMPDIR, chunk);
  const result = split({ source: sourceFile, spec, out: rendered });
  writeFileSync(path.join(dir, "checker.log"), result.log);
  const files = [...owners.values()].sort();
  if (result.status === "certified") {
    const disk = split({ source: sourceFile, spec, out: rendered, checkOutput: true });
    assert.equal(disk.status, "certified", disk.log);
    assert.deepEqual(disk.verdict, result.verdict);
    tally.certified++;
    for (const modulePath of files) {
      const ordinals = nodes.flatMap((node, index) => (owners.get(node.destination) === modulePath ? [index] : []));
      assertSelectedSourceUnits(
        units.map((unit) => unit.node),
        readFileSync(path.join(rendered, modulePath), "utf8"),
        ordinals,
        `${chunk}/${modulePath}`
      );
    }
  } else {
    assert.equal(result.status, "refused", result.log);
    assert.equal(typeof result.reason, "string", result.log);
    assert(
      files.every((modulePath) => !existsSync(path.join(rendered, modulePath))),
      "refusal emitted no modules"
    );
    tally.refused++;
  }
  const summary = {
    chunk,
    units: nodes.length,
    nonentryModules: owners.size - 1,
    moved: nodes.filter((node) => owners.get(node.destination) !== entry).length,
    rustInversions: validation.swapped_pairs,
    status: result.status,
    scope: result.scope,
    reason: result.reason,
  };
  write("result", summary);
  console.log(JSON.stringify(summary));
}
console.log(JSON.stringify({ outcomeCounts: tally }));
