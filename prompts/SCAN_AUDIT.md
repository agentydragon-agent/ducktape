# Scan Prompts Audit: Mandatory vs Optional Automated Scans

**Generated**: 2025-11-19
**Purpose**: Audit all scan prompts for adherence to mandatory/recommended/optional automation guidelines from PHILOSOPHY.md

## Summary

- **Total Prompts**: 31
- **Currently Mandatory Scans**: 0 (all treat automation as optional/recommended)
- **Have Dedicated Scanners**: 4 (`scan_*.py` scripts)
- **Should Be Mandatory**: 8 (high-recall patterns)
- **Correctly Optional**: 16 (subjective/low-recall patterns)

---

## Detailed Audit Table

| Prompt | Current Status | Should Be | Automated Tool/Pattern | Primary Patterns | Notes |
|--------|---------------|-----------|------------------------|------------------|-------|
| **error-swallowing** | Optional | **MANDATORY** | `scan_error_handling.py` (AST, ~100% recall) | Bare except, `except Exception:`, non-raising handlers, single-line try | AST finds ALL exception handlers |
| **type-ignore-suppressions** | Optional | **MANDATORY** | grep `# type: ignore` (~100% recall) | Type ignore comments, noqa markers, suppression comments | Pattern can ONLY appear as comment |
| **useless-comments-and-docs** | Optional | **MANDATORY** | `scan_comments.py` (AST, ~100% recall) | Duplicate comments, obvious statements, outdated docs | AST finds ALL comments/docstrings |
| **missing-dataclass-pydantic** | Optional | **MANDATORY** | `scan_dataclass_candidates.py` (AST, ~95% recall) | Boilerplate `__init__`, redundant assignments, manual `__repr__/__eq__` | AST finds all classes with `__init__` |
| **manual-serde-needs-pydantic** | Optional | **RECOMMENDED** | `scan_manual_serde.py` (AST, ~80% recall) | Dict literals with string keys, manual serialization, Pydantic opportunities | High false positives (I/O boundaries legitimate) |
| **trivial-forwarders** | Optional | **RECOMMENDED** | grep + AST (~70% recall) | Single-call functions, functions called once, trivial wrappers | Medium recall, context needed |
| **walrus-get-pattern** | Optional | **RECOMMENDED** | grep `dict.get()` + if (~70% recall) | `dict.get()` followed by if, walrus operator opportunities | Common pattern, medium recall |
| **timestamp-naming** | Optional | **RECOMMENDED** | grep `_ts`, `timestamp` (~60% recall) | `_ts` suffix, verbose timestamp names, timestamp field naming | Many variations, medium recall |
| **test-assertions** | Optional | **RECOMMENDED** | grep assert patterns (~65% recall) | Plain asserts vs PyHamcrest, field-by-field assertions | Multiple patterns to search |
| **asyncio-antipatterns** | Optional | **RECOMMENDED** | grep `asyncio.gather`, `asyncio.run` (~60% recall) | `asyncio.gather()` vs TaskGroup, missing async context managers | Multiple antipatterns |
| **pydantic-antipatterns** | Optional | **RECOMMENDED** | grep Pydantic methods (~65% recall) | Manual `model_dump`, dict-style access, field iteration | Various antipatterns |
| **stringly-typed** | Optional | **RECOMMENDED** | AST string counter + grep (~65% recall) | String literals instead of enums/Literal, categorical strings | Context needed to confirm |
| **suspicious-nullability** | Optional | **RECOMMENDED** | grep `None` + AST (~60% recall) | Nullable params/returns, None propagation, impossible None | Requires semantic analysis |
| **unnecessary-verbosity** | Optional | OPTIONAL | AST analyzer (~50% recall) | Single-use variables, verbose boolean returns, redundant conditionals | Subjective, context required |
| **useless-test-classes** | Optional | OPTIONAL | grep test classes (~40% recall) | Test classes without setup/fixtures, container classes | Hard to detect automatically |
| **trivial-forwarder-methods** | Optional | OPTIONAL | Manual review | Method forwarding, property wrappers, delegation | Requires understanding intent |
| **api-model-design** | Optional | OPTIONAL | Manual review | Denormalized/computed fields, API design issues | Architectural, subjective |
| **denormalized-computed-fields** | Optional | OPTIONAL | Manual review | Denormalized fields, redundant computation | Context and domain knowledge |
| **duplicated-test-code** | Optional | OPTIONAL | Manual review | Duplicated test code, copy-paste tests | Similarity detection complex |
| **fastmcp-documentation-patterns** | Optional | OPTIONAL | Manual review | FastMCP docs, docstring formatting | Domain-specific, subjective |
| **functional-over-imperative** | Optional | OPTIONAL | Manual review | Imperative loops vs comprehensions, functional patterns | Style preference, subjective |
| **identifier-naming** | Optional | OPTIONAL | Manual review | Naming consistency, conventions, clarity | Highly subjective |
| **legacy-aliases** | Optional | OPTIONAL | Manual review | Deprecated names, backward compat aliases | Project-specific |
| **library-type-misuse** | Optional | OPTIONAL | Manual review | Wrong API usage, incorrect patterns | Library-specific knowledge |
| **methods-vs-freestanding** | Optional | OPTIONAL | Manual review | Method vs function choices, factory patterns | Architectural decision |
| **mypy-appeasing-code** | Optional | OPTIONAL | Manual review | Type narrowing workarounds, mypy hacks | Requires type system understanding |
| **overly-loose-typing** | Optional | OPTIONAL | Manual review | `Any` types, loose annotations | Subjective, context required |
| **pygit2-patterns** | Optional | OPTIONAL | Manual review | Idiomatic pygit2 usage, API patterns | Library-specific |
| **pytest-tmp-paths** | Optional | OPTIONAL | Manual review | tmpdir abuse, tmp_path misuse | Requires test understanding |
| **suspicious-defaults** | Optional | OPTIONAL | Manual review | Mutable defaults, surprising defaults | Context-dependent |
| **useless-documentation** | Optional | OPTIONAL | Manual review | Useless docs, redundant docstrings | Subjective quality judgment |

---

## Recommendations by Category

### ✅ MANDATORY Scans (4) - Should require automated scan as first step

1. **error-swallowing** → `scan_error_handling.py`
   - **Why**: AST finds 100% of exception handlers, pattern can only appear in try-except
   - **Action**: Update prompt to say "MANDATORY first step: Run scan_error_handling.py"

2. **type-ignore-suppressions** → grep `# type: ignore`
   - **Why**: Pattern can ONLY appear as comment, 100% recall with grep
   - **Action**: Update prompt to say "MUST run grep to find ALL type ignore comments"

3. **useless-comments-and-docs** → `scan_comments.py`
   - **Why**: AST finds 100% of comments/docstrings
   - **Action**: Update prompt to say "MANDATORY: Run scan_comments.py to extract ALL comments"

4. **missing-dataclass-pydantic** → `scan_dataclass_candidates.py`
   - **Why**: AST finds ~95% of classes with `__init__`, manual search impractical
   - **Action**: Update prompt to say "MANDATORY: Run scan_dataclass_candidates.py"

### ⚠️ RECOMMENDED Scans (9) - Should suggest but not require

Medium-recall tools (60-80%) that help narrow candidates but aren't comprehensive:

- manual-serde-needs-pydantic
- trivial-forwarders
- walrus-get-pattern
- timestamp-naming
- test-assertions
- asyncio-antipatterns
- pydantic-antipatterns
- stringly-typed
- suspicious-nullability

**Action**: Update prompts to say "RECOMMENDED (but not required): Run [tool/grep pattern]"

### ✅ OPTIONAL Scans (18) - Correctly treat automation as hints

Low-recall or subjective patterns where automation provides hints only:

- All manual review prompts (architectural, style, naming, etc.)
- Patterns requiring domain knowledge or semantic understanding
- Quality judgments that can't be automated

**Action**: No changes needed, correctly labeled as optional

---

## Priority Updates

### High Priority (Update These First)

1. **error-swallowing.md** - Add "MANDATORY first step" language
2. **type-ignore-suppressions.md** - Add "MUST run grep" language
3. **useless-comments-and-docs.md** - Add "MANDATORY: scan_comments.py" language
4. **missing-dataclass-pydantic.md** - Add "MANDATORY: scan_dataclass_candidates.py" language

### Medium Priority

Update 9 RECOMMENDED prompts to clarify automation is helpful but not required

### Low Priority

Review optional prompts to ensure they don't accidentally imply automation is sufficient

---

## Template Examples

### MANDATORY Language

```markdown
## Detection Strategy

**MANDATORY first step**: Run `scan_error_handling.py` to find ALL exception handlers.

- Tool has ~100% recall - finds every try-except block via AST
- Cannot skip this step - manual search will miss instances across large codebase
- Output provides line numbers and handler types for verification

**Why mandatory**: Exception handlers can ONLY appear in try-except blocks, and AST parsing finds them all with 100% recall. Skipping this scan means missing real issues.
```

### RECOMMENDED Language

```markdown
## Detection Strategy

**RECOMMENDED (but not required)**: Run grep patterns to identify common cases.

- Medium recall (~70%) - finds typical patterns but misses variations
- High false positive rate - many findings are legitimate
- Use to narrow down files worth manual review

**Supplemental approach**: Manual code reading required regardless, as grep has medium recall.
```

### OPTIONAL Language

```markdown
## Detection Strategy

**Optional automation**: AST tool can flag short variable names as hints.

- Low recall (~30%) - misses most issues requiring context
- Manual code review is the primary detection method
- Use tool only to help prioritize which files to read first

**Primary approach**: Manual reading of codebase with focus on [specific areas].
```

---

## Conclusion

**Current State**: All 31 prompts treat automation as optional/recommended, even for high-recall tools.

**Recommended Changes**:
- 4 prompts should make automation MANDATORY (100% recall patterns)
- 9 prompts should clarify automation is RECOMMENDED (60-80% recall)
- 18 prompts correctly treat automation as OPTIONAL (subjective/low-recall)

**Next Steps**: Update the 4 high-priority prompts to require automated scans as first step, preventing agents from skipping high-recall tools.
