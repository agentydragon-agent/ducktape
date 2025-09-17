# Merge unverified issues into canonical issues file

@README.md

From context, you should see that we are working with some particular piece of code, and gathering issues that are present in it.

## Canonical issues format (Jsonnet)

- The canonical issues live in `issues.libsonnet` (rootV2: source, scope, items).
- Use the helpers in `src/adgn_llm/properties/specimens/lib.libsonnet`:
  - `I.issueOneOccurrence(...)` for a single cross‑cutting issue with `filesToRanges={path: [ranges] | null}`
  - `I.issueOccurrencesFromLines(...)` for many independent instances with `linesByFile={path: [line|[start,end], ...]}`
- Coverage semantics:
  - `should_flag=true` and `properties!=[]` → covered by an existing property
  - `should_flag=true` and `properties==[]` → not covered yet (gap)
  - `should_flag=false` → canonical negative (do‑not‑flag)
- Rationale MUST be a text block (||| … |||) wrapped to ~100 columns.
- Property slugs MUST be added only when the code violates the definition wording exactly as written under `definitions/**.md`.

We have:

* One central **canonical issues** file: `issues.libsonnet` where we gather:
  * canonical descriptions of issues I've validated (should_flag=true),
  * canonical negatives (should_flag=false).
* A bunch of other **gathered issue files** in the same directory (freeform). They are unverified and may include duplicates.

## Main loop

Start by explaining your understanding of the context:

- Where is the **canonical issues** file (issues.libsonnet)
- Where are the **gathered issue files**
- Where is the source code which is being criticized by these issues

Ask me to confirm that your understanding is correct.

Once we're in sync, read each **gathered issue file** and present to me each issue it contains.
For each gathered issue:

1. Describe it and show the subject code (include multiple examples if repeated). Include code before (with the issue) and a sketched “after” when helpful. Do not write to files yet.

2. I will decide the disposition:

   If it’s a true positive (should be in canon):
   * Add a new entry to `issues.libsonnet` using `I.issueOneOccurrence` or `I.issueOccurrencesFromLines` as appropriate.
   * Choose `id` sequentially (iss-###) and preserve ordering.
   * Set `should_flag=true`.
   * Set `properties` to a non‑empty list only if the finding clearly violates a property definition as written; otherwise `[]`.
   * Precisely localize with `files` or `linesByFile` (paths + line/line ranges).
   * Write the rationale as a text block (||| … |||) preserving the important semantics of the user’s description.

   If it’s a canonical negative (false positive):
   * Add as `should_flag=false` with clear rationale, localized anchors, and `properties=[]`.

   If it’s a duplicate or invalid: mark it as such and do not add to canon.

3. After handling an issue, remove duplicates of the handled issue from the gathered files (or mark as merged) and proceed.

