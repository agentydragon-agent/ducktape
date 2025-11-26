# Lint a specimen for conformance

@../../specimens/CLAUDE.md

## What this command does

Lint a specimen directory (and its files) against the authoring rules defined in @../../specimens/CLAUDE.md (which transcludes @../../docs/authoring.md).

**CRITICAL: Examine ALL issues in the specimen, not just a sample.** Unless explicitly instructed to examine only specific issues, the linter must check every `issues/*.libsonnet` file in the specimen.

Report only lints/errors and offer concrete fix suggestions. Do not modify files without explicit user approval.

## Single source of truth

Do not duplicate requirement lists here. The linter MUST read the authoring guide at runtime and derive all rules from it.

## Quality Checklist

The linter should verify ALL items from the "Quality Checklist" section in the authoring guide, including:

### Structure & Organization
- [ ] `manifest.yaml` exists with `source.commit` (full SHA) and `scope` fields
- [ ] All issues in `issues/*.libsonnet` (not scattered elsewhere)
- [ ] **Each `.libsonnet` describes ONE logical problem type** (not multiple unrelated issues)
- [ ] **Same issue across multiple locations = ONE shared issues file** (e.g., all "upgrade to new syntax" occurrences together)
- [ ] README minimal or absent (only cross-cutting context)

### Issue Quality
- [ ] No open research questions (no "Check if X works" or "TODO: investigate")
- [ ] Objective descriptions (no subjective phrasing)
- [ ] Proper Jsonnet helpers used
- [ ] Brief code citations (no blocks >10 lines, use verbal descriptions when sufficient)
- [ ] Issues grouped by logical problem, not location
- [ ] Complete rationale (what's wrong, why, correct approach)
- [ ] Snapshot-only references (rationale only references repo state in specimen snapshot)
- [ ] Standalone issues (each Jsonnet file self-contained without other issue files or non-captured files)

### Jsonnet Style
- [ ] Triple-bar spacing correct (one space before `|||`, two-space indent, closing with comma)
- [ ] Minimal comments (prefer structured fields)
- [ ] Comments only for metadata (describe what cannot fit in structured data fields)
- [ ] No duplicated info in comments
- [ ] Valid syntax (all files compile)

### Frozen Snapshot Principle
- [ ] No resolution status tracking
- [ ] Historical accuracy (describes problems at snapshot commit)
- [ ] Immutable (specimens don't change after creation)

### Bundle Integration
- [ ] Bundle excludes specimens directory (if applicable)
- [ ] No files >2MB in hydrated specimen
- [ ] Scope accurate

## Input
- Target specimen: path to a specimen directory or any file inside it.
  - A valid specimen contains `issues/*.libsonnet` files
  - If omitted, discover candidates via `specimens/*/` directories

## Output
A textual report of all violations with:
- Location: file path and line number(s)
- Rule reference: quote from authoring guide
- Suggested fix: concrete edit description

## Procedure
1) Read authoring guide and extract checklist
2) Identify target specimen directory
3) Validate structure and files
4) **Use `adgn-properties2 specimen-exec <slug> -- <command>` for ALL interactions with the hydrated specimen** to ensure proper isolation and correct specimen hydration
5) **Check EVERY issue file in `issues/*.libsonnet`** (not just a sample):
   - Evaluate Jsonnet to JSON
   - Verify ONE logical issue per file
   - Check if same issue appears in multiple files (should be consolidated)
   - Validate against schema
   - Check for unnecessary code blocks (use verbal descriptions when sufficient)
   - Verify rationale only references snapshot state (no historical context)
   - Ensure issue is standalone (no dependencies on other issues or non-captured files)
6) Check README (if present) for minimal content
7) Emit violations with references and suggested fixes
8) Ask user to confirm which fixes to apply

**Note:** Unless the user explicitly asks to examine only specific issues (e.g., "lint issues 001-005"), you must check all issue files in the specimen.

## Interaction with Specimens

**CRITICAL**: Always use `adgn-properties2 specimen-exec <slug> -- <command>` when you need to interact with the hydrated specimen code:
- Reading files from the specimen
- Running tools against the specimen code
- Checking file existence or structure

This ensures:
- Proper specimen hydration (git checkout at correct commit)
- Isolation from the host filesystem
- Correct working directory context

Example:
```bash
# Read a file from specimen
adgn-properties2 specimen-exec ducktape/2025-11-20-repo -- cat adgn/tests/agent/test_foo.py

# Check if file exists
adgn-properties2 specimen-exec ducktape/2025-11-20-repo -- test -f adgn/src/adgn/agent/bar.py && echo "exists"

# List files matching pattern
adgn-properties2 specimen-exec ducktape/2025-11-20-repo -- find adgn -name "*.py" -type f
```
