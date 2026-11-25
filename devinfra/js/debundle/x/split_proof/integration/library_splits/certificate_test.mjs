import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { topLevelStatements } from "../../translation/scope_metadata.mjs";
import { spec } from "./gen_spec.mjs";
import { split } from "../../translation/testing/split.mjs";
import { smoke } from "./smoke.mjs";

const results = [];
const tmp = process.env.TEST_TMPDIR;

function certificate(input, options = {}) {
  return split({ ...input, ...options, structural: true });
}

function extract(n, unit) {
  return {
    entry: "entry.mjs",
    modules: {
      "entry.mjs": Array.from({ length: n }, (_, i) => i)
        .filter((i) => i !== unit)
        .map((i) => `#${i}`),
      "moved.mjs": [`#${unit}`],
    },
  };
}

function inputs(source, name, placement) {
  const file = path.join(tmp, name + ".json");
  writeFileSync(file, JSON.stringify(placement));
  const out = path.join(tmp, name);
  return { source, spec: file, out };
}

for (const source of process.argv.slice(2)) {
  const library = path.basename(source, ".mjs");
  const units = topLevelStatements(JSON.parse(readFileSync(source.slice(0, -4) + ".json", "utf8")));
  const n = units.length;
  const baseline = await smoke(library, source);
  assert(baseline.ok, JSON.stringify(baseline));

  const placements = [
    ["halves", spec(n, "halves")],
    ["advance-second", extract(n, 1)],
  ];
  const firstFunction = units.findIndex(({ node }, i) => i > 0 && node.type === "FunctionDeclaration");
  if (firstFunction !== -1) placements.push(["advance-function", extract(n, firstFunction)]);
  for (const [strategy, placement] of placements) {
    const args = inputs(source, library + "-" + strategy, placement);
    const verdict = certificate(args);
    if (verdict.status === "refused") {
      // A refusal without an observed difference is inconclusive.
      assert.equal(verdict.scope, "linked-structural");
      assert(!existsSync(args.out));
      assert.equal(strategy, "advance-second", JSON.stringify(verdict.verdict));
      results.push({ library, strategy, outcome: "unknown", reason: verdict.reason });
    } else {
      if (strategy === "advance-function") assert.equal(verdict.scope, "linked-structural-pivot");
      assert.deepEqual(certificate(args, { checkOutput: true }).verdict, verdict.verdict);
      assert.deepEqual(await smoke(library, path.join(args.out, placement.entry)), baseline);
      results.push({ library, strategy, outcome: "certified", scope: verdict.scope });
    }
  }
  if (library === "semver") {
    const host = path.join(tmp, "portable.json");
    writeFileSync(host, JSON.stringify({ profile: "ecmascript", stableIntrinsicValues: ["Object.defineProperty@1"] }));
    const placement = extract(n, 1);
    const args = inputs(source, "semver-portable", placement);
    const verdict = certificate(args, { hostContract: host });
    assert.equal(verdict.status, "certified", JSON.stringify(verdict.verdict));
    assert.equal(verdict.scope, "linked-structural-pivot");
    assert.equal(verdict.verdict.hostProfile, "ecmascript");
    assert.match(
      verdict.verdict.assumptions.join("\n"),
      /Object\.defineProperty@1:.*intrinsic\.Object\.defineProperty.*no observable effects/
    );
    assert.deepEqual(certificate(args, { hostContract: host, checkOutput: true }).verdict, verdict.verdict);
    assert.deepEqual(await smoke(library, path.join(args.out, placement.entry)), baseline);
    results.push({
      library,
      strategy: "advance-second-portable",
      outcome: "certified",
      scope: verdict.scope,
      assumptions: verdict.verdict.assumptions,
    });
  }
}

assert(results.some((row) => row.strategy === "advance-function" && row.outcome === "certified"));

// Use the same advance-second placement. Both graphs finish normally, but the
// moved initializer reads the linked var cell before the entry assigns 1.
const source = path.join(tmp, "control.mjs");
writeFileSync(source, "var current = 1; var observed = current; export { current, observed };");
const placement = extract(3, 1);
const args = inputs(source, "early-read", placement);
const refused = certificate(args);
assert.equal(refused.status, "refused");
assert(!existsSync(args.out));
assert(refused.reason, "the refused temporal-order change has a recorded reason");
results.push({
  library: "control",
  strategy: "advance-second",
  outcome: "rejected",
  reason: refused.reason,
});

const lines = results.map((row) => JSON.stringify(row)).join("\n") + "\n";
writeFileSync(path.join(process.env.TEST_UNDECLARED_OUTPUTS_DIR, "certificates.jsonl"), lines);
process.stdout.write(lines);
