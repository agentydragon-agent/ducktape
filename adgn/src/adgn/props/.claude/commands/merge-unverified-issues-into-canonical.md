# Merge unverified issues into canonical issues file

@README.md

From context, you should see that we are working with some particular piece of code, and gathering issues that are present in it.

## Canonical issues format (Jsonnet)

- The canonical issues live in `issues.libsonnet` (rootV2: source, scope, items).
- Use the helpers in `src/adgn_llm/properties/specimens/lib.libsonnet`:
  - `I.issue(...)` for a single logical occurrence (one or more files with filesToRanges)
  - `I.issueMulti(...)` for multiple independent occurrences (each with files, note, expect_caught_from)
- Issue classification:
  - `should_flag=true` → real issues that should be flagged
  - `should_flag=false` → canonical negative (do‑not‑flag)
- Rationale MUST be a text block (||| … |||) wrapped to ~100 columns.

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

   If it's a true positive (should be in canon):
   * Add a new entry to `issues.libsonnet` using `I.issue` or `I.issueMulti` as appropriate.
   * Choose `id` sequentially (iss-###) and preserve ordering.
   * Set `should_flag=true`.
   * Precisely localize with `filesToRanges` (for I.issue) or per-occurrence `files` (for I.issueMulti).
   * Write the rationale as a text block (||| … |||) preserving the important semantics of the user's description.
   * For multi-file issues: specify `expect_caught_from` (required).

   If it's a canonical negative (false positive):
   * Add as `should_flag=false` with clear rationale and localized anchors.

   If it’s a duplicate or invalid: mark it as such and do not add to canon.

3. After handling an issue, remove duplicates of the handled issue from the gathered files (or mark as merged) and proceed.

