import assert from "node:assert/strict";
import test from "node:test";
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
