import assert from "node:assert/strict";
import test from "node:test";
import { parse } from "@babel/parser";
import { analyzeRuntimeBoundaryAst } from "../analysis/boundary.mjs";
import { planSelectedAtomicModules } from "./planner.mjs";

test("planSelectedAtomicModules rejects unknown selected owner ids that appear in access edges", () => {
  const analysis = {
    owners: [
      {
        id: "owner_known",
        memberWritesTopLevel: { eager: [], lazy: [] },
        names: ["KnownOwner"],
        ordinal: 0,
        readsTopLevel: { eager: [], lazy: [] },
        type: "VariableDeclaration",
        writesTopLevel: {
          eager: [{ kind: "local_declaration", ownerId: "owner_missing" }],
          lazy: [],
        },
      },
    ],
    programItems: [{ id: "owner_known", ordinal: 0 }],
    sideEffects: [],
  };

  assert.throws(
    () =>
      planSelectedAtomicModules(
        {
          analysis,
          code: "const KnownOwner = 1;",
          itemMetricsById: new Map([
            [
              "owner_known",
              {
                bytes: 21,
                lines: 1,
              },
            ],
          ]),
        },
        {
          selectedOwnerIds: ["owner_known", "owner_missing"],
        }
      ),
    /unknown owner ids outside analysis\.owners: owner_missing/
  );
});

test("planSelectedAtomicModules splits lazy callable and pure constant declarators within one top-level declaration", () => {
  const ast = parse(
    `const alpha = "a", buildBeta = function buildBeta() { return alpha; }, gamma = "g";
function readBuildBeta() {
  return buildBeta();
}
export { readBuildBeta };`,
    { sourceType: "module" }
  );
  const analysis = analyzeRuntimeBoundaryAst(ast, { chunkId: "static/app" });

  const plan = planSelectedAtomicModules(
    {
      analysis,
      code: null,
      programBody: ast.program.body,
    },
    {}
  );

  const fragments = plan.atomicUnits.flatMap((unit) => unit.ownerFragments ?? []);
  assert.ok(fragments.some((fragment) => fragment.memberNames.includes("alpha")));
  assert.ok(fragments.some((fragment) => fragment.memberNames.includes("buildBeta")));
  assert.ok(fragments.some((fragment) => fragment.memberNames.includes("gamma")));
  assert.ok(
    fragments.some(
      (fragment) =>
        fragment.kind === "variable_declarator" && fragment.memberNames.length === 1 && fragment.memberNames[0] === "buildBeta"
    )
  );
});

test("planSelectedAtomicModules does not split declarators across eager top-level intra-owner reads", () => {
  const ast = parse(
    `const alpha = beta, beta = function beta() { return "b"; };
export { alpha, beta };`,
    { sourceType: "module" }
  );
  const analysis = analyzeRuntimeBoundaryAst(ast, { chunkId: "static/app" });

  const plan = planSelectedAtomicModules(
    {
      analysis,
      code: null,
      programBody: ast.program.body,
    },
    {}
  );

  const ownerWithAlphaAndBeta = plan.atomicUnits.find((unit) => unit.memberNames.includes("alpha") && unit.memberNames.includes("beta"));
  assert.ok(ownerWithAlphaAndBeta);
  assert.equal(ownerWithAlphaAndBeta.ownerFragments?.length ?? 0, 0);
});
