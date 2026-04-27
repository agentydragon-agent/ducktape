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
