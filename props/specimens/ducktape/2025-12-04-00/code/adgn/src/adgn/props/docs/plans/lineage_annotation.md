# LineRange Annotations Design

## Overview

This document describes the design for adding inline annotations (comments/notes) to individual line ranges within issue occurrences. Currently, notes can only be attached at the Occurrence level, but fine-grained per-line annotations would improve clarity and reduce verbosity in rationale text.

## Current State

### Pydantic Schema (models/issue.py)

```python
class LineRange(BaseModel):
    start_line: int = Field(..., ge=1, description="1-based start line number")
    end_line: int | None = Field(
        default=None, description="1-based end line number (inclusive); omit for single-line anchor"
    )
```

- No annotation field on LineRange
- Notes can only be attached at the Occurrence level via `Occurrence.note`

### Jsonnet Helpers (specimens/lib.libsonnet)

Current shorthand support in `occFromEntry()`:
- `123` → single line (no note)
- `[123, 155]` → range (no note)
- `[123, "note"]` → single line with **occurrence-level** note
- `[123, 155, "note"]` → range with **occurrence-level** note

The notes are attached to the Occurrence, not to individual LineRange objects.

## Proposed Design

### 1. Pydantic Schema Changes

Add an optional `note` field to `LineRange`:

```python
class LineRange(BaseModel):
    start_line: int = Field(..., ge=1, description="1-based start line number")
    end_line: int | None = Field(
        default=None, description="1-based end line number (inclusive); omit for single-line anchor"
    )
    note: str | None = Field(
        default=None,
        description="Optional inline annotation/comment for this specific line range"
    )

    @model_validator(mode="after")
    def _validate_range(self) -> LineRange:
        if self.start_line < 1:
            raise ValueError("start_line must be >= 1")
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line when provided")
        return self

    model_config = ConfigDict(extra="forbid")
```

### 2. Jsonnet Helper Changes

Update `toRange()` to handle annotated line specs:

```jsonnet
// Normalize a line spec into a LineRange object.
// Accepts:
//   - int (single line)
//   - [start, end] (range)
//   - [line, "note"] (single line with annotation)
//   - [start, end, "note"] (range with annotation)
//   - object with start_line/end_line/note fields
local toRange(x) =
  if std.type(x) == 'number' then
    { start_line: x }
  else if std.type(x) == 'array' && std.length(x) == 2 then (
    if std.type(x[1]) == 'number' then
      // [start, end] - range without note
      { start_line: x[0], end_line: x[1] }
    else if std.type(x[1]) == 'string' then
      // [line, "note"] - single line with note
      { start_line: x[0], note: x[1] }
    else
      error 'Invalid 2-element array spec: ' + std.manifestJson(x)
  )
  else if std.type(x) == 'array' && std.length(x) == 3 then (
    if std.type(x[0]) == 'number' && std.type(x[1]) == 'number' && std.type(x[2]) == 'string' then
      // [start, end, "note"] - range with note
      { start_line: x[0], end_line: x[1], note: x[2] }
    else
      error 'Invalid 3-element array spec: ' + std.manifestJson(x)
  )
  else if std.type(x) == 'object' && std.objectHas(x, 'start_line') then
    x
  else
    error 'Invalid line spec: ' + std.manifestJson(x);
```

### 3. Semantic Distinction

**Two levels of notes:**

1. **LineRange.note** (new): Inline annotation for a specific code location
   - Short, contextual comment about what's at that location
   - Example: "main validation logic", "error handling", "config parsing"
   - Keep brief - just enough to distinguish this location from others

2. **Occurrence.note** (existing): Explanation for this occurrence as a whole
   - Why this occurrence is significant or unique
   - How it differs from other occurrences of the same issue
   - When to use: multi-file occurrences, special context needed

**Usage guidelines:**
- Prefer LineRange notes for simple location labels
- Use Occurrence notes when multiple files/ranges need collective explanation
- Don't duplicate rationale - put global explanation in `IssueCore.rationale`

### 4. Example Usage

```jsonnet
local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale=|||
    Manual JSON parsing without schema validation.
    Should use Pydantic TypeAdapter for automatic validation.
  |||,
  filesToRanges={
    'src/app.py': [
      [45, "user config parsing"],           // Single line with note
      [78, 92, "API response handling"],     // Range with note
      [120],                                  // Single line without note
      [200, 210],                             // Range without note
    ],
  },
)
```

With occurrence-level note:

```jsonnet
I.issueWithOccurrences(
  rationale=|||
    Dead code that should be removed.
  |||,
  occurrences=[
    {
      files: {
        'src/utils.py': [
          [45, "unused helper function"],
          [78, 92, "dead import section"],
        ],
      },
      note: "These were part of the old caching system before refactor"
    },
  ],
)
```

### 5. Migration Path

**Backward compatibility:**
- Existing specimens without line notes continue to work (note field is optional)
- Existing occurrence-level notes are unchanged
- No data migration required for existing issues

**Adoption:**
- New specimens can use line-level notes for clarity
- Existing specimens can be gradually enhanced if needed
- Consider line notes when occurrence note would just list locations

### 6. Implementation Tasks

1. **Pydantic schema** (models/issue.py):
   - Add `note: str | None` field to `LineRange`
   - Update tests to cover annotated line ranges

2. **Jsonnet helpers** (specimens/lib.libsonnet):
   - Update `toRange()` to parse `[line, "note"]` and `[start, end, "note"]`
   - Update documentation/examples
   - Add tests for annotated line specs

3. **Validation**:
   - Ensure line notes are preserved through load/dump cycles
   - Test Jsonnet evaluation with annotated ranges
   - Verify backward compatibility with existing specimens

4. **Documentation**:
   - Update specimens/CLAUDE.md with line annotation examples
   - Update jsonnet_authoring.md guidelines
   - Add usage examples to key documentation

## Alternatives Considered

### Alternative 1: Dict-based line specs
Use dict form in Jsonnet: `{start: 123, end: 155, note: "text"}`

**Rejected because:**
- More verbose than array shorthand
- Loses conciseness of current `[start, end]` notation
- Inconsistent with existing array-based pattern

### Alternative 2: Separate annotations dict
Keep LineRange simple, add `annotations: dict[tuple[int, int | None], str]` to Occurrence

**Rejected because:**
- Awkward tuple keys in JSON/Jsonnet
- Complicates lookup and validation
- Less ergonomic for authoring

### Alternative 3: Keep everything in occurrence notes
Continue using only occurrence-level notes with inline text

**Rejected because:**
- Causes verbosity in rationale and occurrence notes
- Makes programmatic extraction harder
- Doesn't provide structured location context

## Open Questions

1. **Character limit for line notes?**
   - Recommendation: Keep them brief (< 100 chars), but don't enforce hard limit
   - Longer explanations should go in occurrence note or rationale

2. **Should line notes support markdown?**
   - Initial answer: Plain text only for simplicity
   - Can be enhanced later if needed

3. **UI rendering?**
   - Line notes should appear inline with code locations
   - Consider truncation/tooltip for long notes
   - Out of scope for this design (UI enhancement)

## References

- Current LineRange: src/adgn/props/models/issue.py:8-22
- Jsonnet helpers: src/adgn/props/specimens/lib.libsonnet:18-27
- Occurrence schema: src/adgn/props/models/issue.py:25-58
