# Scan Prompt TODO

## Philosophy Compliance

✅ **ALL SCAN PROMPTS UPDATED** - All 17 scan prompts now follow the philosophy:

1. `useless-documentation.md` - Code skeleton generation approach
2. `stringly-typed.md` - General strategies over hardcoded lists
3. `unnecessary-verbosity.md` - AST-based detection with manual verification
4. `test-assertions.md` - PyHamcrest patterns with philosophy
5. `pygit2-patterns.md` - Idiomatic patterns guide
6. `mypy-appeasing-code.md` - Research-first workflow for casts
7. `asyncio-antipatterns.md` - Context-dependent blocking detection
8. `pydantic-antipatterns.md` - Detection Strategy with manual review
9. `trivial-forwarders.md` - Comprehensive decision framework with recall/precision
10. `manual-serde-needs-pydantic.md` - Detection Strategy with context analysis
11. `vague-field-names.md` - Semantic analysis formalized
12. `library-type-misuse.md` - Read source methodology
13. `api-model-design.md` - Context-dependent detection
14. `trivial-forwarder-methods.md` - Detection Strategy added
15. `timestamp-naming.md` - Convention-based detection
16. `pytest-tmp-paths.md` - Simple pattern detection
17. `denormalized-computed-fields.md` - Domain model analysis (just updated)

## Update Template

For each remaining prompt, add before the grep/AST patterns:

```markdown
## Detection Strategy

**Primary Method**: Manual code reading. [Context-specific guidance]

**Why automation is insufficient**: [Specific reason for this pattern - e.g.,
"Determining if a field name is 'vague' requires understanding domain context
and whether the container name provides sufficient clarity"]

**Discovery aids** (high false positive rate - manual verification required):

### Grep Patterns / AST Analysis
[Existing patterns, clearly labeled as discovery only]
```

## Philosophy Document

See `prompts/PHILOSOPHY.md` for the complete philosophy and guidelines all scan prompts should follow.

**Key principles**:
- Manual reading is primary method
- Automated tools are discovery aids only
- Prefer high recall with manual filtering over low recall with auto-fix
- General strategies beat hardcoded specific patterns
- High-level descriptions of AST tools, not full implementations
