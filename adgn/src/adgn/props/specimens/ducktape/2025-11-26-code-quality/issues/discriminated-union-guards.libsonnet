local I = import '../../specimens/lib.libsonnet';

// iss-020: Discriminated union type guards should use proper zod validation

I.issueOneOccurrence(
  rationale= |||
    Lines 8-9 in ToolExec.svelte and ToolJson.svelte use manual discriminated union type
    guards (checking `content_kind === 'Exec'`) instead of proper Zod validation against
    schemas generated from Pydantic models.

    **Problems:**
    1. String literal comparison is fragile (no runtime validation)
    2. Type assertion doesn't validate structure
    3. TypeScript types can drift from Python Pydantic models
    4. Manual type guards instead of generated validators
    5. Misleading comment says "type-safe" but only does string comparison

    **Correct approach:**
    Use Zod schemas generated from Pydantic discriminated unions. Validate with Zod's
    safeParse instead of manual type guards. This provides runtime validation, eliminates
    drift, and enables proper type narrowing.

    **Implementation:**
    Extend the generator at `adgn/scripts/generate_frontend_code.py` to output Zod schemas.
    Two approaches:

    **Option 1:** Use `json-schema-to-zod` (https://www.npmjs.com/package/json-schema-to-zod)
    to convert JSON Schema (already generated via `TypeAdapter(model).json_schema()`) into
    Zod schema code. Since Pydantic's JSON Schema includes discriminator metadata, this
    should handle discriminated unions correctly.

    **Option 2:** Detect `discriminator` field in Pydantic's JSON Schema output and emit
    Zod code directly (e.g., `z.discriminatedUnion("content_kind", [...])`).

    Option 1 is simpler and leverages existing tooling.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ToolExec.svelte': [
      [8, 8],  // Manual type guard for Exec content
    ],
    'adgn/src/adgn/agent/web/src/components/ToolJson.svelte': [
      [9, 9],  // Manual type guard for Json content
    ],
  },
)
