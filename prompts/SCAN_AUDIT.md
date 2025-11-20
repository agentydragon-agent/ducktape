# Scan Prompts Audit: Missing Mandatory Scans

**Last Updated**: 2025-11-20

## Status Summary

- **Total Scan Prompts**: 30
- **With MANDATORY Step 0**: 16 ✅
- **Still Missing MANDATORY**: 14 ❌

## Prompts Still Missing MANDATORY Scans

The following prompts do NOT have "MANDATORY Step 0" detection strategies. They should either:
1. Add MANDATORY scans if high-recall automation is available, OR
2. Explicitly document why automation is insufficient (subjective patterns, low recall, context-dependent)

### 1. api-model-design.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Architectural decisions, subjective API design choices
- **Status**: Correctly optional - no concrete scan would prevent lazy analysis

### 2. denormalized-computed-fields.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Requires domain knowledge to identify denormalization
- **Status**: Correctly optional - context-dependent

### 3. error-swallowing.md ❌
- **Current**: Has `scan_error_handling.py` (AST scanner) but not marked MANDATORY
- **Should add**: MANDATORY Step 0 requiring scan_error_handling.py
- **Why**: ~100% recall for all exception handlers, prevents lazy "looks fine" claims
- **Action needed**: Add MANDATORY language

### 4. identifier-naming.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Highly subjective naming preferences
- **Status**: Correctly optional - no scan prevents subjective judgment

### 5. legacy-aliases.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Project-specific deprecated names
- **Status**: Correctly optional - requires project history knowledge

### 6. library-type-misuse.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Library-specific knowledge required
- **Status**: Correctly optional - no general scan available

### 7. manual-serde-needs-pydantic.md ❌
- **Current**: Has `scan_manual_serde.py` (AST scanner) but not marked MANDATORY
- **Should add**: MANDATORY Step 0 requiring scan_manual_serde.py
- **Why**: High recall for dict construction patterns and Pydantic models
- **Action needed**: Add MANDATORY language

### 8. methods-vs-freestanding.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Architectural decisions about code organization
- **Status**: Correctly optional - subjective design choices

### 9. mypy-appeasing-code.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Requires understanding type system workarounds
- **Status**: Correctly optional - context-dependent

### 10. pydantic-antipatterns.md ❌
- **Current**: Has grep patterns for union types but not marked MANDATORY
- **Should add**: MANDATORY Step 0 for union type + isinstance scans
- **Why**: High recall for Pydantic type system defeats
- **Action needed**: Add MANDATORY language

### 11. timestamp-naming.md ❌
- **Current**: Optional/manual review with suggested grep
- **Reason for no MANDATORY**: Medium recall, style preference
- **Status**: Correctly optional - naming is subjective

### 12. trivial-forwarder-methods.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Requires understanding delegation intent
- **Status**: Correctly optional - architectural context needed

### 13. unnecessary-verbosity.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Subjective judgment about verbosity
- **Status**: Correctly optional - style preference

### 14. useless-comments-and-docs.md ❌
- **Current**: Has `scan_comments.py` (AST scanner) but not marked MANDATORY
- **Should add**: MANDATORY Step 0 requiring scan_comments.py
- **Why**: ~100% recall for all comments/docstrings
- **Action needed**: Add MANDATORY language

### 15. useless-test-classes.md ❌
- **Current**: Optional/manual review
- **Reason for no MANDATORY**: Requires test context understanding
- **Status**: Correctly optional - no concrete scan available

## Priority Actions

### High Priority - Add MANDATORY Language (4 prompts)

These have high-recall scanners but don't require them:

1. **error-swallowing.md** → Add MANDATORY Step 0 for `scan_error_handling.py`
2. **useless-comments-and-docs.md** → Add MANDATORY Step 0 for `scan_comments.py`
3. **manual-serde-needs-pydantic.md** → Add MANDATORY Step 0 for `scan_manual_serde.py`
4. **pydantic-antipatterns.md** → Add MANDATORY Step 0 for grep-based scans

### Low Priority - Already Correct (10 prompts)

These correctly lack MANDATORY scans due to:
- Subjective judgments (naming, verbosity, design)
- Context-dependent patterns (legacy, library-specific)
- Architectural decisions (methods vs functions, API design)

No action needed for these.

## Summary

**16/30 prompts** (53%) now have MANDATORY Step 0 scans that force agents to review concrete candidates.

**4 prompts** still need MANDATORY language added despite having high-recall scanners.

**10 prompts** correctly remain optional due to subjective/context-dependent nature.
