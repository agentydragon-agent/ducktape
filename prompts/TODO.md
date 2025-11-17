# Scan Prompt TODO

## Philosophy Compliance

The following scan prompts **have been updated** to follow the philosophy (manual reading first, automation as discovery aids):

✅ **Updated** (7/17):
1. `useless-documentation.md` - Code skeleton generation approach
2. `stringly-typed.md` - General strategies over hardcoded lists
3. `unnecessary-verbosity.md` - Simplified from full AST implementations
4. `test-assertions.md` - Emphasizes PyHamcrest patterns with context
5. `pygit2-patterns.md` - API reference with idiomatic patterns
6. `mypy-appeasing-code.md` - Research-first workflow for casts
7. `asyncio-antipatterns.md` - Context-dependent blocking detection

## Remaining Prompts to Update

The following prompts need "Detection Strategy" sections added following the philosophy:

**High Priority** (frequently used):
- `pydantic-antipatterns.md` - Very short, easy to add philosophy section
- `trivial-forwarders.md` - Has AST code, needs philosophy framing
- `manual-serde-needs-pydantic.md` - Has AST/grep, needs manual-first emphasis
- `vague-field-names.md` - Has "semantic analysis" note, formalize as Detection Strategy

**Medium Priority**:
- `library-type-misuse.md` - Has "read source" methodology, formalize philosophy
- `api-model-design.md` - Pattern-focused, add context-dependent detection note

**Low Priority** (simple/rarely used):
- `trivial-forwarder-methods.md`
- `timestamp-naming.md`
- `pytest-tmp-paths.md`
- `denormalized-computed-fields.md`

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
