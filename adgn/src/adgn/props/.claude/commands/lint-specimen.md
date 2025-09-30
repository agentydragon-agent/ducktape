# Lint a specimen for conformance

@README.md

## What this command does

Lint a specimen directory (and its files) against the rules defined in this package’s @README.md (see “Specimens format”).
Report only lints/errors and offer concrete fix suggestions. Do not modify files without explicit user approval.

## Single source of truth

Do not duplicate requirement lists here. The linter MUST read @README.md at runtime and derive all rules from it.
Primary sections to parse:
- “Specimens format” (General, Files, issues.libsonnet rootV2)
- “Conventions” (apply where relevant)
- Any other sections that normatively constrain specimen structure/content

Also treat `issues.libsonnet` (canonical issues) as the authoritative ground‑truth format:
- Evaluate Jsonnet to JSON using python‑jsonnet; fail if evaluation errors occur
- Validate each item against SpecimenIssues schema (id, should_flag, rationale text block, properties, files/linesByFile)
- Enforce: rationale is a Jsonnet text block (||| … |||) wrapped ~100 cols; properties only when a definition is clearly violated as written; cardinality rules respected (single vs multi_instances)
- Cross‑check property slugs against `definitions/**.md` filenames

## Property definitions adherence

The agent MUST read every property definition Markdown file under `properties/**.md` and apply them exactly:
- Treat each property file as the authoritative definition (frontmatter + predicate + acceptance criteria + examples).
- Items in `covered.md` MUST reference a property only when the finding clearly satisfies that property's definition; do not classify using tangentially related properties.
- For each `covered.md` item, extract and quote the specific acceptance criterion (or predicate/example) that justifies the match. If you cannot cite a matching line, flag as “Property mismatch (tangential)” and suggest moving the item to `not_covered_yet.md` or choosing a correct property.
- Validate property links: they MUST resolve to actual files under `properties/**`; IDs/paths must be correct.
- Apply Markdown properties under `properties/markdown/**` to all specimen Markdown files (README.md, covered.md, not_covered_yet.md, false_positives.md).

## Input
- Target specimen: path to a specimen directory or any file inside it.
  - A valid specimen contains `issues.libsonnet` (rootV2: source, scope, items).
  - If omitted, discover candidates via `specimens/*/issues.libsonnet` and `todo-specimen/*/issues.libsonnet`.

## Output
A textual report of all violations of @README.md.

For each case, include:
- Location: file path and line number(s) where applicable
- Rule reference: a minimal quote + pointer to @README.md section (and line(s) if convenient)
- Suggested fix: a minimal edit description to conform

## Scope of checks
Derive all specifics directly from @README.md at runtime (do not restate here).

## Procedure
1) Read @README.md and extract a checklist of required vs recommended items for specimens.
2) Identify target specimen directory:
   - If given a file path, resolve its containing specimen directory
   - Otherwise, discover candidates via `specimens/*/issues.libsonnet` and `todo-specimen/*/issues.libsonnet`
3) Validate directory and naming.
4) Validate required files and schema (evaluate `issues.libsonnet` to JSON; validate rootV2: {source, scope, items}).
5) Validate per-file rules for README.md (if present), covered.md, not_covered_yet.md, false_positives.md, and general constraints; for covered.md, verify each item’s property link is justified by quoting the exact acceptance criterion (or predicate/example) from the property definition; if no exact supporting line can be cited, flag as property mismatch and recommend moving to not_covered_yet.md or correcting the link.
6) For each violation, emit: one‑line diagnosis, short quoted rule reference from @README.md, and a suggested fix.
7) Print the report and suggested changes. Do not write changes yet — ask user to confirm which (if any) to apply.
