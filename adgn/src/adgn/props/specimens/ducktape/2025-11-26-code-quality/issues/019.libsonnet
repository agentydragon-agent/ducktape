local I = import '../../specimens/lib.libsonnet';

// iss-019: Use pydantic->ts generator with zod instead of JSON.parse with loose types

I.issueOneOccurrence(
  rationale= |||
    Lines 84-92 in ChatPane.svelte use `JSON.parse(firstContent.text) as AgentList`
    with a TypeScript type assertion instead of runtime validation with Zod schemas.

    **Problems:**
    1. No runtime validation - `as AgentList` is compile-time only
    2. Silent failures - invalid JSON structure causes runtime errors or wrong data
    3. Type drift - TypeScript types can drift from Python Pydantic models
    4. Duplicate definitions - maintaining parallel type definitions is error-prone
    5. Missing Zod generation - the pydantic->ts generator needs to output Zod schemas

    **Correct approach:**
    Replace `JSON.parse(text) as AgentList` with Zod validation using schemas generated
    from Pydantic models. This provides runtime safety, eliminates drift, and gives
    detailed validation errors.

    **Implementation:**
    Extend the generator at `adgn/scripts/generate_frontend_code.py` to output Zod
    schemas alongside TypeScript interfaces. Use `json-schema-to-zod`
    (https://www.npmjs.com/package/json-schema-to-zod) or `ts-to-zod`
    (https://www.npmjs.com/package/ts-to-zod) to convert JSON Schema (already generated
    via `model_json_schema()`) into Zod schema code.

    Then replace all `JSON.parse(text) as Type` patterns with
    `TypeZ.safeParse(JSON.parse(text))` throughout the codebase.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [
      [84, 92],  // JSON.parse with loose type assertion
    ],
  },
)
