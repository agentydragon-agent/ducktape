import assert from "node:assert/strict";
import test from "node:test";
import { runTransformSpecObject } from "./runner.mjs";

test("runTransformSpecObject rejects the retired extract_ordered_init_regions stage", async () => {
  await assert.rejects(
    runTransformSpecObject({
      kind: "js.ast_transform_spec",
      pipeline: [
        {
          id: "legacy_extract",
          operation: "extract_ordered_init_regions",
        },
      ],
    }),
    /No registered stage handler for operation extract_ordered_init_regions/
  );
});

test("runTransformSpecObject rejects the retired rename_bindings stage", async () => {
  await assert.rejects(
    runTransformSpecObject({
      kind: "js.ast_transform_spec",
      pipeline: [
        {
          id: "legacy_rename",
          operation: "rename_bindings",
        },
      ],
    }),
    /No registered stage handler for operation rename_bindings/
  );
});

test("runTransformSpecObject rejects the retired extract_runtime_boundary_metadata stage", async () => {
  await assert.rejects(
    runTransformSpecObject({
      kind: "js.ast_transform_spec",
      pipeline: [
        {
          id: "legacy_boundary",
          operation: "extract_runtime_boundary_metadata",
        },
      ],
    }),
    /No registered stage handler for operation extract_runtime_boundary_metadata/
  );
});

test("runTransformSpecObject rejects the retired extract_atomic_modules stage", async () => {
  await assert.rejects(
    runTransformSpecObject({
      kind: "js.ast_transform_spec",
      pipeline: [
        {
          id: "legacy_atomic",
          operation: "extract_atomic_modules",
        },
      ],
    }),
    /No registered stage handler for operation extract_atomic_modules/
  );
});

test("runTransformSpecObject rejects the retired merge_modules stage", async () => {
  await assert.rejects(
    runTransformSpecObject({
      kind: "js.ast_transform_spec",
      pipeline: [
        {
          id: "legacy_merge",
          operation: "merge_modules",
        },
      ],
    }),
    /No registered stage handler for operation merge_modules/
  );
});
