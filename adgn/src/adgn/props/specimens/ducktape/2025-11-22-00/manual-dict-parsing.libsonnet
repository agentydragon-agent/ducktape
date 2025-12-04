local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The `parse_event()` function manually parses event dictionaries using if-elif
    chains that inspect the `type` field and construct the appropriate payload class.
    This is exactly what Pydantic's discriminated union parsing does automatically,
    but the code reimplements it by hand.

    **Current implementation (events.py, lines 67-100):**
    The code defines `TypedPayload` with `Field(discriminator=None)` and implements
    a 30+ line `parse_event()` function with manual if-elif dispatching for each
    event type (USER_TEXT, ASSISTANT_TEXT, TOOL_CALL, etc.), manually extracting
    fields from dictionaries and constructing payload objects.

    **Problems:**

    1. **Reimplements Pydantic**: Manual if-elif dispatching duplicates what Pydantic does
    2. **Error-prone**: Easy to forget cases or mismatch type strings
    3. **Verbose**: 30 lines of manual parsing vs 3 lines with discriminated unions
    4. **No validation**: Manual `str()` casts and `.get()` don't validate structure
    5. **Inconsistent**: Some fields use TypeAdapter, others use manual dict access
    6. **Misleading type hint**: `Field(discriminator=None)` suggests discriminated union but doesn't use it
    7. **Maintenance burden**: Adding a new event type requires updating if-elif chain

    **The correct approach:**

    Use Pydantic's discriminated union parsing: add `Literal["type"]` to each
    payload class, set `Field(discriminator="type")` on the union, and use
    `model_validate()`. This reduces the 30+ line manual parser to a 3-line
    function that injects the type field into the payload dict before validation.

    **Benefits:**

    1. **Automatic dispatch**: Pydantic handles type-based routing
    2. **Full validation**: All fields validated according to payload schema
    3. **Type safety**: Type checkers understand the discriminated union
    4. **Concise**: 3 lines instead of 30+ lines of if-elif
    5. **Better errors**: ValidationError shows exactly what's wrong
    6. **Easy to extend**: Add new event type = add new payload class to union
    7. **Declarative**: Schema describes what's valid, not how to parse
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/events.py': [
      [47, 50],  // TypedPayload union with discriminator=None
      [67, 100], // Manual parse_event() with if-elif chains
    ],
  },
)
