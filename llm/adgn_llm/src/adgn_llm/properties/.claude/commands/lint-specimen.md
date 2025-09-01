# Lint a specimen README for conformance

@README.md

## What this command does

Lint a specimen’s README.md against the rules defined in this package’s @README.md.
Report only lints/errors and offer concrete fix suggestions. Do not modify files without explicit user approval.

## Input
- Target specimen: path to either a specimen directory (containing README.md) or directly to a README.md file.
  - If omitted, list selectable candidates under `specimens/**/README.md` and `todo-specimen/**/README.md`.

## Output
A textual report with list of cases where a specimen's README.md violates specifications in main-level README.md on how specimen README.md's should be formatted.

For each case:
- Location: file path and line number(s) where applicable
- Rule reference: quote the minimal relevant excerpt from @README.md with a line reference (e.g., “Specimens format → Free-form structure …”)
- Suggested fix: a minimal edit description and summary of how you'd edit the specimen README to conform

## Checks (derived from @README.md)
Derive required and recommended checks by parsing @README.md, specifically the sections:
- “Specimens format” (location, naming, free‑form structure)
- “Conventions”
- Any other sections that normatively specify specimen README structure or content

## Procedure
1) Read @README.md and extract a checklist of required vs recommended items for specimen READMEs.
2) Locate the target README.md, read and parse its headings and sections.
3) Validate against the derived checklist:
   - Presence/absence of required sections; ordering; title format
   - Path/name conformance of the specimen directory/file (date+slug)
   - Link/pointer style conformance when @README.md prescribes it
   - Any additional normative constraints you found
4) For each violation, produce:
   - A one‑line diagnosis
   - A short quoted rule reference from @README.md
   - A suggested fix.
5) Print the report and suggested changes. Do not write changes yet - ask user to confirm which (if any) to apply.
