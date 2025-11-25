# Add findings to specimen

@README.md

## What this command does

Add new confirmed findings into a specimen.
If unclear on which specimen you should add to, ask the user to clarify.

Preserve the semantics given to you in the issue descriptions - they may be important for context.
Do not shorten unduly, err on the side of preserving context and explanation of what's wrong and why.

Use checked out source code of the specimen - read code user submits issues on to understand the issues
yourself and submit a good description.

## Canonical issues format (Jsonnet)

The canonical ground-truth file is `issues.libsonnet` (rootV2). Use the Jsonnet helpers in
src/adgn_llm/properties/specimens/lib.libsonnet:

- I.issueOneOccurrence(...) for a single cross-cutting issue (one occurrence with filesToRanges={path: [ranges] | null})
- I.issueOccurrencesFromLines(...) for many independent occurrences (one per lineSpec) using
  linesByFile={path: [line or [start,end], ...]}

Required fields per issue:
- id: stable string like iss-001 (sequential; keep order meaningful)
- should_flag: true for real issues; false for canonical do-not-flag
- rationale: multiline text block (||| ... |||) wrapped ~100 cols; keep exact user language when provided
- files / linesByFile: precise localization; prefer exact line ranges; use null only when genuinely unspecified

Cardinality guidelines:
- Use multi_instances when there are many independent occurrences (imports at top, pathlike misuse across files)
- Use single when it’s one conceptual cross-cutting problem (a duplicated flow within one file; a dead module)

Issue classification:
- should_flag=true  → real issues that should be flagged
- should_flag=false → canonical negative (do-not-flag)

Examples (Jsonnet):

```jsonnet
// Many inline imports across files
I.issueOccurrencesFromLines(
  rationale=|||
  Inline imports inside functions that have no reason to be lazy. Move to module top.
  |||,
  linesByFile={'pkg/a.py': [101, 158], 'pkg/b.py': [[10, 12]]},
),

// Single cross-cutting duplication within one file
I.issueOneOccurrence(
  rationale=|||
  Duplicate hydration/post-creation script invocation paths; consolidate on production path.
  |||,
  filesToRanges={'app/service.py': [[98, 164], [299, 380]]},
),
```

Make sure to properly respect classification into:

- `covered.md` (= issues that are violations of already existing properties - in `props/**`),
- `not_covered.md` (= issues that would not clearly fall under already existing properties),
- `false_positives.md` (properties some critique flagged that are not actually problematic).

User may give you a mix. Make sure to properly classify each issue.

**IMPORTANT**: Stick to the **ACTUAL** wording of the props **AS THEY EXIST** in `props/**.md`.
Do not invent new non-existant properties. Do not stretch props beyond what the wording clearly says.
If a finding only tangentially touches on a property but someone just asked "find every place this code
violates this property" would not clearly point it out as "yes, here the property definition is clearly violated",
it does not fall under that property.

## Process

1. Read **ALL** property definition files in `props/**.md` to make sure you know the *actual definition wording*.
2. Find if we have the source code of the specimen already checked out. Ensure the specimen contains `issues.libsonnet`; use any `work` subdir if present, or hydrate fresh per tooling.
3. Check if finding submitted by user is already documented; if it is, omit it and tell the user.
4. Add finding to the proper file (`covered/not_covered/false_positives.md`) following guidelines in @README.md.
