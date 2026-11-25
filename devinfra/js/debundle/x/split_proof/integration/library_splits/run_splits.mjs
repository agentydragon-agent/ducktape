// Many splits of one real bundle: what the Lean checker says, and what Node does with the split program.
//
//   node run_splits.mjs <bundle> <strategy> [--bundles DIR] [--step N] [--seeds N] [--jobs N] [--out results.jsonl]
//
//   bundle    lodash | acorn | semver | zod | acorn.min | zod.min   (../../../lowering/bundles/<bundle>.{json,mjs})
//   strategy  halves | cuts | cuts_entry_first | blocks | random
//             cuts:   every single cut point c = step, 2*step, … (two modules [0, c) and [c, n))
//             cuts_entry_first: the same cuts, but the first module is the entry
//             blocks: k = 2…8 contiguous blocks
//             random: k ∈ {2, 3, 5, 8} modules, `seeds` random assignments each
//
// Each split is checked by the certified command. Refusals are recorded without output; certified files are passed
// to `smoke.mjs`. One JSON line per split records the certificate verdict and (for accepted plans) the Node result.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { copyFile, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as acorn from "acorn";
import { topLevelStatements } from "../../translation/scope_metadata.mjs";
import { spec as makeSpec } from "./gen_spec.mjs";
import { split } from "../../translation/testing/split.mjs";
import { smoke } from "./smoke.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
process.env.LOWERSPLIT ??= path.resolve(path.join(here, "../../lean/.lake/build/bin/lowersplit"));

const [bundle, strategy, ...rest] = process.argv.slice(2);
const option = (name, fallback) => {
  const at = rest.indexOf(`--${name}`);
  return at < 0 ? fallback : rest[at + 1];
};
const lowering = path.resolve(option("bundles", path.join(here, "../../lowering/bundles")));
const step = Number(option("step", 1));
const seeds = Number(option("seeds", 20));
const jobs = Number(option("jobs", 4));
const resultFile = option("out", `${bundle}_${strategy}.jsonl`);
const family = bundle.replace(/\.min$/, "");

const bundleJson = JSON.parse(await readFile(path.join(lowering, `${bundle}.json`), "utf8"));
const n = topLevelStatements(bundleJson).length;
const baseline = JSON.stringify(await smoke(family, path.join(lowering, `${bundle}.mjs`)));
if (!JSON.parse(baseline).ok) throw new Error(`the bundle itself fails its smoke test: ${baseline}`);

const plans = [];
if (strategy === "halves") plans.push({ strategy, args: [] });
else if (strategy === "cuts") for (let c = step; c < n; c += step) plans.push({ strategy: "cut", args: [c] });
else if (strategy === "cuts_entry_first")
  for (let c = step; c < n; c += step)
    plans.push({ strategy: "cut", args: [c, "entry-first"], label: "cut_entry_first" });
else if (strategy === "blocks") for (let k = 2; k <= 8; k++) plans.push({ strategy, args: [k] });
else if (strategy === "random")
  for (const k of [2, 3, 5, 8]) for (let seed = 1; seed <= seeds; seed++) plans.push({ strategy, args: [k, seed] });
else throw new Error(`unknown strategy ${strategy}`);

const lines = [];
const tally = {};
let next = 0;
function moduleEvaluationOrder(directory, entry) {
  const visited = new Set();
  const order = [];
  function visit(file) {
    if (visited.has(file)) return;
    visited.add(file);
    const program = acorn.parse(readFileSync(path.join(directory, file), "utf8"), {
      sourceType: "module",
      ecmaVersion: "latest",
    });
    for (const node of program.body) {
      if (node.type !== "ImportDeclaration") continue;
      const dependency = path.posix.normalize(path.posix.join(path.posix.dirname(file), node.source.value));
      if (existsSync(path.join(directory, dependency))) visit(dependency);
    }
    order.push(file);
  }
  visit(entry);
  return order;
}
async function worker() {
  while (next < plans.length) {
    const plan = plans[next++];
    const dir = await mkdtemp(path.join(tmpdir(), "split_"));
    try {
      const spec = makeSpec(n, plan.strategy, plan.args);
      const specFile = path.join(dir, "spec.json");
      await writeFile(specFile, JSON.stringify(spec));
      const output = path.join(dir, "out");
      const checked = split({
        ast: path.join(lowering, `${bundle}.json`),
        spec: specFile,
        out: output,
        structural: true,
      });
      const certified = checked.status === "certified";
      let node = "not-run";
      let detail = checked.reason ?? "";
      let reordered = null;
      if (certified) {
        const got = await smoke(family, path.join(output, spec.entry));
        node = JSON.stringify(got) === baseline ? "same" : "different";
        detail = node === "same" ? "" : got.ok ? "returned a different value" : got.error;
        const executionOrder = moduleEvaluationOrder(output, spec.entry).flatMap((file) => spec.modules[file] ?? []);
        reordered = executionOrder.some((unit, i) => Number(unit.slice(1)) !== i);
        if (node !== "same") {
          await copyFile(
            path.join(dir, "spec.json"),
            `${resultFile}.${plan.strategy}-${plan.args.join("-")}.spec.json`
          );
        }
      } else {
        assert(!existsSync(output), "certified refusal published modules");
      }
      const line = {
        bundle,
        strategy: plan.label ?? plan.strategy,
        args: plan.args,
        modules: Object.keys(spec.modules).length,
        verdict: checked.status,
        scope: checked.scope,
        reason_code: checked.reasonCode,
        reason: checked.reason,
        reordered,
        node,
        detail,
      };
      lines.push(line);
      const key = certified ? `certified/${node}` : "refused";
      tally[key] = (tally[key] ?? 0) + 1;
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  }
}
await Promise.all(Array.from({ length: jobs }, worker));
// the workers finish in any order: one order for every run keeps a rerun's diff to what changed
const order = (a, b) =>
  a.args.length - b.args.length || a.args.reduce((d, x, i) => d || (x < b.args[i] ? -1 : x > b.args[i] ? 1 : 0), 0);
await writeFile(
  resultFile,
  lines
    .sort(order)
    .map((l) => `${JSON.stringify(l)}\n`)
    .join("")
);
console.log(`${bundle} ${strategy}: ${plans.length} splits`, tally);
if (tally["certified/different"]) {
  console.error("UNSOUND: a certified split behaves differently");
  process.exitCode = 1;
}

if (rest.includes("--require-accepted") && !tally["certified/same"]) throw new Error("no certified matching split");
