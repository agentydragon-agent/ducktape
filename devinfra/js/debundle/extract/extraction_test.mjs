import assert from "node:assert/strict";
import test from "node:test";
import { parse } from "@babel/parser";
import { analyzeRuntimeBoundaryAst } from "../analysis/boundary.mjs";
import {
  buildLogicalModulePlans,
  closeSelectedOwnerIdsOverDependencyGraph,
  logicalSelectedOwnerIdsForChunk,
} from "./logical_modules.mjs";
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

test("planSelectedAtomicModules splits inert class declarators with only lazy intra-owner reads", () => {
  const ast = parse(
    `const beta = "b", Delta = class Delta {
  static label() {
    return beta + ":" + Delta.name;
  }
};
export { beta, Delta };`,
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
  assert.ok(fragments.some((fragment) => fragment.memberNames.length === 1 && fragment.memberNames[0] === "beta"));
  assert.ok(fragments.some((fragment) => fragment.memberNames.length === 1 && fragment.memberNames[0] === "Delta"));
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

test("planSelectedAtomicModules does not split class declarators across eager class-definition reads", () => {
  const ast = parse(
    `const Base = class Base {}, Derived = class Derived extends Base {};
export { Base, Derived };`,
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

  const ownerWithBaseAndDerived = plan.atomicUnits.find(
    (unit) => unit.memberNames.includes("Base") && unit.memberNames.includes("Derived")
  );
  assert.ok(ownerWithBaseAndDerived);
  assert.equal(ownerWithBaseAndDerived.ownerFragments?.length ?? 0, 0);
});

test("planSelectedAtomicModules can split declarator fragments around attached side effects that touch only one fragment", () => {
  const ast = parse(
    `const createPlatformClient = () => ({ ok: true }), indexedDbOutgoingTxSendQueue = new Map();
window.indexedDbSendQueue = indexedDbOutgoingTxSendQueue;
export { createPlatformClient, indexedDbOutgoingTxSendQueue };`,
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

  const createPlatformClientUnit = plan.atomicUnits.find((unit) => unit.memberNames.includes("createPlatformClient"));
  const indexedDbQueueUnit = plan.atomicUnits.find((unit) => unit.memberNames.includes("indexedDbOutgoingTxSendQueue"));

  assert.ok(createPlatformClientUnit);
  assert.ok(indexedDbQueueUnit);
  assert.notEqual(createPlatformClientUnit.id, indexedDbQueueUnit.id);
  assert.equal(createPlatformClientUnit.attachedItemIds.length, 0);
  assert.equal(indexedDbQueueUnit.attachedItemIds.length, 1);
  assert.ok(
    createPlatformClientUnit.ownerFragments?.some(
      (fragment) => fragment.kind === "variable_declarator" && fragment.memberNames[0] === "createPlatformClient"
    )
  );
  assert.ok(
    indexedDbQueueUnit.ownerFragments?.some(
      (fragment) =>
        fragment.kind === "variable_declarator_group" &&
        fragment.memberNames.length === 1 &&
        fragment.memberNames[0] === "indexedDbOutgoingTxSendQueue"
    )
  );
});

test("logicalSelectedOwnerIdsForChunk expands direct logical members through the full owner dependency graph", () => {
  const ast = parse(
    `const independentValue = "independent";
const focusLabel = "focus";
class FocusService {
  static label() {
    return focusLabel;
  }
}
function useFocusService() {
  return FocusService.label();
}
function readIndependentValue() {
  return independentValue;
}
export { useFocusService, readIndependentValue };`,
    { sourceType: "module" }
  );
  const analysis = analyzeRuntimeBoundaryAst(ast, { chunkId: "static/app" });

  const selectedOwnerIds = logicalSelectedOwnerIdsForChunk(
    [
      {
        id: "logical__focus_service",
        operation: "define_logical_module",
        selector: {
          chunkId: "static/app",
        },
        target: {
          path: "ui/focus/service",
        },
        members: [
          {
            id: "member__use_focus_service",
            name: "useFocusService",
            selector: {
              binding: {
                kind: "FunctionDeclaration",
                name: "useFocusService",
              },
            },
          },
        ],
      },
    ],
    { analysis, chunkId: "static/app" }
  );

  const selectedNames = new Set(
    analysis.owners
      .filter((owner) => selectedOwnerIds.has(owner.id))
      .flatMap((owner) => owner.names)
  );
  assert.ok(selectedNames.has("useFocusService"));
  assert.ok(selectedNames.has("FocusService"));
  assert.ok(selectedNames.has("focusLabel"));
  assert.ok(!selectedNames.has("independentValue"));
  assert.ok(!selectedNames.has("readIndependentValue"));
});

test("closeSelectedOwnerIdsOverDependencyGraph repairs an arbitrary preselected owner base", () => {
  const ast = parse(
    `const focusLabel = "focus";
class FocusService {
  static label() {
    return focusLabel;
  }
}
function useFocusService() {
  return FocusService.label();
}
export { useFocusService };`,
    { sourceType: "module" }
  );
  const analysis = analyzeRuntimeBoundaryAst(ast, { chunkId: "static/app" });
  const useFocusServiceOwnerId = analysis.owners.find((owner) => owner.names.includes("useFocusService"))?.id;
  assert.ok(useFocusServiceOwnerId);

  const selectedOwnerIds = closeSelectedOwnerIdsOverDependencyGraph([useFocusServiceOwnerId], {
    analysis,
    callerName: "test closeSelectedOwnerIdsOverDependencyGraph",
  });
  const selectedNames = new Set(
    analysis.owners
      .filter((owner) => selectedOwnerIds.has(owner.id))
      .flatMap((owner) => owner.names)
  );
  assert.ok(selectedNames.has("useFocusService"));
  assert.ok(selectedNames.has("FocusService"));
  assert.ok(selectedNames.has("focusLabel"));
});

test("buildLogicalModulePlans closes explicit modules over dependent atomic modules", () => {
  const analysis = {
    owners: [
      {
        id: "owner_00001",
        memberWritesTopLevel: { eager: [], lazy: [] },
        names: ["symbolFor", "failExpected"],
        ordinal: 0,
        readsTopLevel: { eager: [], lazy: [] },
        type: "VariableDeclaration",
        writesTopLevel: { eager: [], lazy: [] },
      },
      {
        id: "owner_00002",
        memberWritesTopLevel: { eager: [], lazy: [] },
        names: ["addDisposableResource", "disposeResources"],
        ordinal: 1,
        readsTopLevel: {
          eager: [],
          lazy: [
            { kind: "local_declaration", name: "symbolFor", ownerId: "owner_00001" },
            { kind: "local_declaration", name: "failExpected", ownerId: "owner_00001" },
          ],
        },
        type: "VariableDeclaration",
        writesTopLevel: { eager: [], lazy: [] },
      },
    ],
  };
  const currentModules = [
    {
      attachedItemIds: [],
      bytes: 32,
      id: "atomic_module_0000",
      index: 0,
      lines: 1,
      memberNames: ["symbolFor", "failExpected"],
      modulePath: "modules/atomic_module_0000",
      nameHint: "providers",
      ownerIds: ["owner_00001"],
      ownerFragments: [],
      startOrdinal: 0,
      unitIds: ["selected_atomic_unit_0000"],
    },
    {
      attachedItemIds: [],
      bytes: 48,
      id: "atomic_module_0001",
      index: 1,
      lines: 1,
      memberNames: ["addDisposableResource", "disposeResources"],
      modulePath: "modules/atomic_module_0001",
      nameHint: "helpers",
      ownerIds: ["owner_00002"],
      ownerFragments: [],
      startOrdinal: 1,
      unitIds: ["selected_atomic_unit_0001"],
    },
  ];
  const operations = [
    {
      id: "logical__runtime_helpers",
      operation: "define_logical_module",
      selector: {
        chunkId: "static/app",
      },
      target: {
        path: "runtime/helpers",
      },
      members: [
        {
          id: "member__dispose_resources",
          name: "disposeResources",
          selector: {
            binding: {
              kind: "VariableDeclarator",
              name: "disposeResources",
            },
            owner: {
              id: "owner_00002",
            },
          },
        },
      ],
    },
    {
      id: "logical__residual",
      operation: "define_residual_module",
      selector: {
        chunkId: "static/app",
      },
      target: {
        path: "residual/unhandled",
      },
    },
  ];

  const plan = buildLogicalModulePlans(currentModules, operations, {
    analysis,
    chunkId: "static/app",
    targetDir: "modules",
  });
  const runtimeHelpers = plan.modules.find((modulePlan) => modulePlan.modulePath === "runtime/helpers");
  assert.ok(runtimeHelpers);
  assert.deepEqual(runtimeHelpers.ownerIds, ["owner_00001", "owner_00002"]);
  assert.deepEqual(
    runtimeHelpers.atomicBoundaryUnits.map((unit) => unit.id),
    ["atomic_module_0000", "atomic_module_0001"]
  );
  assert.equal(plan.counts.residualModules, 0);
});

test("buildLogicalModulePlans does not let one incompatible atomic module poison an otherwise extractable path", () => {
  const analysis = {
    owners: [
      {
        currentExtractorCompatible: true,
        id: "owner_00001",
        memberWritesTopLevel: { eager: [], lazy: [] },
        names: ["isElectronUserAgent"],
        ordinal: 0,
        readsTopLevel: { eager: [], lazy: [] },
        type: "FunctionDeclaration",
        writesTopLevel: { eager: [], lazy: [] },
      },
      {
        currentExtractorCompatible: false,
        id: "owner_00002",
        memberWritesTopLevel: { eager: [], lazy: [] },
        names: ["unsupportedSchemaHelper"],
        ordinal: 1,
        readsTopLevel: { eager: [], lazy: [] },
        type: "VariableDeclaration",
        writesTopLevel: { eager: [], lazy: [] },
      },
    ],
  };
  const currentModules = [
    {
      attachedItemIds: [],
      bytes: 24,
      id: "atomic_module_0000",
      index: 0,
      lines: 1,
      memberNames: ["isElectronUserAgent"],
      modulePath: "modules/atomic_module_0000",
      nameHint: "electron",
      ownerIds: ["owner_00001"],
      ownerFragments: [],
      startOrdinal: 0,
      unitIds: ["selected_atomic_unit_0000"],
    },
    {
      attachedItemIds: [],
      bytes: 24,
      id: "atomic_module_0001",
      index: 1,
      lines: 1,
      memberNames: ["unsupportedSchemaHelper"],
      modulePath: "modules/atomic_module_0001",
      nameHint: "schema",
      ownerIds: ["owner_00002"],
      ownerFragments: [],
      startOrdinal: 1,
      unitIds: ["selected_atomic_unit_0001"],
    },
  ];
  const operations = [
    {
      id: "logical__schema_language_core",
      operation: "define_logical_module",
      selector: {
        chunkId: "static/app",
      },
      target: {
        path: "local_api/contract/schema_language_core",
      },
      members: [
        {
          id: "member__electron_user_agent",
          name: "isElectronUserAgent",
          selector: {
            binding: {
              kind: "FunctionDeclaration",
              name: "isElectronUserAgent",
            },
            owner: {
              id: "owner_00001",
            },
          },
        },
        {
          id: "member__unsupported_helper",
          name: "unsupportedSchemaHelper",
          selector: {
            binding: {
              kind: "VariableDeclarator",
              name: "unsupportedSchemaHelper",
            },
            owner: {
              id: "owner_00002",
            },
          },
        },
      ],
    },
    {
      id: "logical__residual",
      operation: "define_residual_module",
      selector: {
        chunkId: "static/app",
      },
      target: {
        path: "residual/unhandled",
      },
    },
  ];

  const plan = buildLogicalModulePlans(currentModules, operations, {
    analysis,
    chunkId: "static/app",
    targetDir: "modules",
  });
  const schemaCore = plan.modules.find((modulePlan) => modulePlan.modulePath === "local_api/contract/schema_language_core");
  assert.ok(schemaCore);
  assert.deepEqual(schemaCore.ownerIds, ["owner_00001"]);
  assert.equal(plan.counts.unmatchedMembers, 1);
});

test("buildLogicalModulePlans excludes a compatible-looking atomic module when it depends on an unavailable atomic", () => {
  const analysis = {
    owners: [
      {
        currentExtractorCompatible: false,
        id: "owner_00001",
        memberWritesTopLevel: { eager: [], lazy: [] },
        names: ["unsupportedProvider"],
        ordinal: 0,
        readsTopLevel: { eager: [], lazy: [] },
        type: "VariableDeclaration",
        writesTopLevel: { eager: [], lazy: [] },
      },
      {
        currentExtractorCompatible: true,
        id: "owner_00002",
        memberWritesTopLevel: { eager: [], lazy: [] },
        names: ["compatibleConsumer"],
        ordinal: 1,
        readsTopLevel: {
          eager: [],
          lazy: [{ kind: "local_declaration", name: "unsupportedProvider", ownerId: "owner_00001" }],
        },
        type: "FunctionDeclaration",
        writesTopLevel: { eager: [], lazy: [] },
      },
    ],
  };
  const currentModules = [
    {
      attachedItemIds: [],
      bytes: 24,
      id: "atomic_module_0000",
      index: 0,
      lines: 1,
      memberNames: ["unsupportedProvider"],
      modulePath: "modules/atomic_module_0000",
      nameHint: "provider",
      ownerIds: ["owner_00001"],
      ownerFragments: [],
      startOrdinal: 0,
      unitIds: ["selected_atomic_unit_0000"],
    },
    {
      attachedItemIds: [],
      bytes: 24,
      id: "atomic_module_0001",
      index: 1,
      lines: 1,
      memberNames: ["compatibleConsumer"],
      modulePath: "modules/atomic_module_0001",
      nameHint: "consumer",
      ownerIds: ["owner_00002"],
      ownerFragments: [],
      startOrdinal: 1,
      unitIds: ["selected_atomic_unit_0001"],
    },
  ];
  const operations = [
    {
      id: "logical__consumer",
      operation: "define_logical_module",
      selector: {
        chunkId: "static/app",
      },
      target: {
        path: "runtime/consumer",
      },
      members: [
        {
          id: "member__consumer",
          name: "compatibleConsumer",
          selector: {
            binding: {
              kind: "FunctionDeclaration",
              name: "compatibleConsumer",
            },
            owner: {
              id: "owner_00002",
            },
          },
        },
      ],
    },
    {
      id: "logical__residual",
      operation: "define_residual_module",
      selector: {
        chunkId: "static/app",
      },
      target: {
        path: "residual/unhandled",
      },
    },
  ];

  const plan = buildLogicalModulePlans(currentModules, operations, {
    analysis,
    chunkId: "static/app",
    targetDir: "modules",
  });
  assert.equal(plan.counts.explicitModules, 0);
  assert.equal(plan.counts.unmatchedMembers, 1);
});
