# Lint a specimen for conformance

@../../specimens/CLAUDE.md

## What this command does

Lint a specimen directory (and its files) against the authoring rules defined in @../../specimens/CLAUDE.md (which transcludes @../../docs/authoring.md).

**CRITICAL: Examine ALL issues in the specimen, not just a sample.** Unless explicitly instructed to examine only specific issues, the linter must check every `issues/*.libsonnet` file in the specimen.

Report only lints/errors and offer concrete fix suggestions. Do not modify files without explicit user approval.

## Single source of truth

Do not duplicate requirement lists here. The linter MUST read the authoring guide at runtime and derive all rules from it.

@../../docs/quality-checklist.md

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
4) **Use `adgn-properties snapshot exec <slug> -- <command>` for ALL interactions with the hydrated specimen** to ensure proper isolation and correct specimen hydration
5) **Check EVERY issue file in `issues/*.libsonnet`** (not just a sample):
   - Evaluate Jsonnet to JSON
   - **Verify ONE logical problem per file** (Authoring Guide §3):
     - Each file should describe ONE logical problem type (e.g., "missing type annotations", "dead code")
     - If an issue describes multiple INDEPENDENT problems at one location, it should be split
     - Example violation: Issue combining "use ternary" (style) AND "architectural bundling problem" (design)
   - **Check if same logical problem appears in multiple files** (should be consolidated):
     - Same problem type across different locations = ONE issue with multiple occurrences
     - Example: "Unnecessary intermediate variables" appearing in issues 003, 009, 023, 028, 045 should be ONE issue
     - Example: "Useless comments" in Python appearing in issues 031, 040, 041 should be ONE issue
   - Validate against schema
   - Check for unnecessary code blocks (use verbal descriptions when sufficient)
   - Verify external references are verifiable when needed:
     - **Do need URLs**: Specific tools/packages (e.g., npm packages, PyPI packages), APIs, commit references (full SHA or GitHub permalink), project-specific components/SDKs
     - **Don't need URLs**: Well-known frameworks/standards (e.g., React, Tailwind CSS, PostgreSQL, Python, pytest)
   - Verify rationale only references snapshot state (no historical context)
   - Ensure issue is standalone (no dependencies on other issues or non-captured files)
6) Check README (if present) for minimal content
7) Emit violations with references and suggested fixes
8) Ask user to confirm which fixes to apply

**Note:** Unless the user explicitly asks to examine only specific issues (e.g., "lint issues 001-005"), you must check all issue files in the specimen.

## Interaction with Specimens

**CRITICAL**: Always use `adgn-properties snapshot exec <slug> -- <command>` when you need to interact with the hydrated specimen code:
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
adgn-properties snapshot exec ducktape/2025-11-20-repo -- cat adgn/tests/agent/test_foo.py

# Check if file exists
adgn-properties snapshot exec ducktape/2025-11-20-repo -- test -f adgn/src/adgn/agent/bar.py && echo "exists"

# List files matching pattern
adgn-properties snapshot exec ducktape/2025-11-20-repo -- find adgn -name "*.py" -type f
```
