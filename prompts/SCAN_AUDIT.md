# Scan Prompts Audit: Missing Mandatory Scans

**Last Updated**: 2025-11-20

## Status Summary

- **Total Scan Prompts**: 30
- **With MANDATORY Step 0**: 20 ✅ (67%)
- **Still Missing MANDATORY**: 10 ❌ (33%)

## Prompts Still Missing MANDATORY Scans

The following 10 prompts do NOT have "MANDATORY Step 0" detection strategies. All are correctly optional due to subjective/context-dependent nature.

### Correctly Optional (10 prompts) - No Action Needed

These correctly lack MANDATORY scans - no concrete scans would prevent lazy analysis:

1. **api-model-design.md** ❌
   - Architectural decisions, subjective API design choices

2. **denormalized-computed-fields.md** ❌
   - Requires domain knowledge to identify denormalization

3. **identifier-naming.md** ❌
   - Highly subjective naming preferences

4. **legacy-aliases.md** ❌
   - Project-specific deprecated names, requires history knowledge

5. **library-type-misuse.md** ❌
   - Library-specific knowledge required, no general scan

6. **methods-vs-freestanding.md** ❌
   - Architectural decisions about code organization

7. **mypy-appeasing-code.md** ❌
   - Requires understanding type system workarounds

8. **timestamp-naming.md** ❌
   - Medium recall, style preference

9. **trivial-forwarder-methods.md** ❌
   - Requires understanding delegation intent

10. **unnecessary-verbosity.md** ❌
    - Subjective judgment about verbosity

11. **useless-test-classes.md** ❌
    - Requires test context understanding

## All High-Priority Actions Completed ✅

The 4 prompts with high-recall scanners already have MANDATORY Step 0:

- ✅ **error-swallowing.md** - Line 188: MANDATORY scan_error_handling.py
- ✅ **useless-comments-and-docs.md** - Line 295: MANDATORY scan_comments.py
- ✅ **manual-serde-needs-pydantic.md** - Line 204: MANDATORY scan_manual_serde.py
- ✅ **pydantic-antipatterns.md** - Line 402: MANDATORY grep patterns

## Summary

**20/30 prompts (67%)** now have MANDATORY Step 0 scans that force agents to review concrete candidates.

**10 prompts (33%)** correctly remain optional due to subjective/context-dependent nature where scans cannot prevent lazy analysis.

**All actionable items completed** - no further MANDATORY scans need to be added.
