# Scan Prompts Audit: Mandatory vs Optional Automated Scans

**Generated**: 2025-11-19
**Purpose**: Audit all scan prompts for adherence to mandatory/recommended/optional automation guidelines from PHILOSOPHY.md

## Key Principle

**Mandatory scans force agents to gather and review concrete candidates**, preventing laziness. This isn't primarily about tool recall - it's about ensuring the agent examines specific instances rather than claiming "looks fine" without thorough review.

## Summary

- **Total Prompts**: 31
- **Currently Mandatory Scans**: 6 (updated to include grep-based mandatory scans)
- **Have Dedicated Scanners**: 4 (`scan_*.py` scripts)
- **Should Be Mandatory**: 6 (scans that surface concrete candidates to force review)
- **Correctly Optional**: 18 (subjective patterns where scan doesn't prevent lazy analysis)

---

## Detailed Audit Table

| Prompt | Current Status | Should Be | Automated Tool/Pattern | Primary Patterns | Why This Classification |
|--------|---------------|-----------|------------------------|------------------|-------------------------|
| **error-swallowing** | Optional | **MANDATORY** | `scan_error_handling.py` (AST) | Bare except, `except Exception:`, non-raising handlers | Surfaces every exception handler - forces agent to review each one |
| **useless-comments-and-docs** | Optional | **MANDATORY** | `scan_comments.py` (AST) | Duplicate comments, obvious statements, outdated docs | Surfaces every comment - agent must judge each as useful/useless |
| **missing-dataclass-pydantic** | Optional | **MANDATORY** | `scan_dataclass_candidates.py` (AST) | Boilerplate `__init__`, redundant assignments | Surfaces every class - forces review of init methods across codebase |
| **manual-serde-needs-pydantic** | Optional | **MANDATORY** | `scan_manual_serde.py` (AST) | Dict literals with string keys, Pydantic models | Surfaces concrete instances - forces review of dict construction patterns |
| **type-ignore-suppressions** | Optional | **MANDATORY** | grep `# type: ignore` | Type ignore comments, suppressions | Surfaces every suppression - forces review of each one |
| **trivial-forwarders** | Optional | **RECOMMENDED** | grep + AST | Single-call functions, trivial wrappers | Grep surfaces candidates but agent would search anyway |
| **walrus-get-pattern** | Optional | **RECOMMENDED** | grep `dict.get()` + if | `dict.get()` followed by if | Grep finds common pattern, saves time |
| **timestamp-naming** | Optional | **RECOMMENDED** | grep `_ts`, `timestamp` | Timestamp field naming | Grep surfaces candidates quickly |
| **test-assertions** | Optional | **RECOMMENDED** | grep assert patterns | Plain asserts vs PyHamcrest | Grep finds common cases |
| **asyncio-antipatterns** | Optional | **RECOMMENDED** | grep asyncio methods | `asyncio.gather()` vs TaskGroup | Grep surfaces specific API usage |
| **pydantic-antipatterns** | Optional | **MANDATORY** | grep union types + isinstance | Union types mixing BaseModel with weak types, isinstance checks | Surfaces every union type smell - forces review of Pydantic type usage |
| **stringly-typed** | Optional | **RECOMMENDED** | AST string counter + grep | String literals instead of enums | Tool helps prioritize files |
| **suspicious-nullability** | Optional | **RECOMMENDED** | grep `None` + AST | Nullable params, None propagation | Grep surfaces candidates for analysis |
| **unnecessary-verbosity** | Optional | OPTIONAL | Manual review | Single-use variables, verbose returns | Subjective judgment, scan doesn't prevent lazy analysis |
| **useless-test-classes** | Optional | OPTIONAL | Manual review | Test classes without setup | Context required, no concrete candidates |
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

### ✅ MANDATORY Scans (6) - Should require automated scan as first step

These scans surface concrete candidates that force the agent to review specific instances rather than claiming "looks fine" without thorough examination.

1. **error-swallowing** → `scan_error_handling.py`
   - **Why mandatory**: Surfaces every exception handler with line numbers - forces agent to review each one
   - **Prevents**: Agent skipping exception handling review, claiming code is fine without checking
   - **Action**: Update prompt to say "MANDATORY first step: Run scan_error_handling.py"

2. **useless-comments-and-docs** → `scan_comments.py`
   - **Why mandatory**: Surfaces every comment/docstring - agent must judge each as useful/useless
   - **Prevents**: Agent reading only obvious cases, missing outdated/duplicate comments
   - **Action**: Update prompt to say "MANDATORY: Run scan_comments.py to extract ALL comments"

3. **missing-dataclass-pydantic** → `scan_dataclass_candidates.py`
   - **Why mandatory**: Surfaces every class with metrics - forces comprehensive review across codebase
   - **Prevents**: Agent only checking a few files, missing boilerplate in less-obvious places
   - **Action**: Update prompt to say "MANDATORY: Run scan_dataclass_candidates.py"

4. **manual-serde-needs-pydantic** → `scan_manual_serde.py`
   - **Why mandatory**: Surfaces every dict literal and Pydantic model - forces pattern review
   - **Prevents**: Agent missing dict construction patterns scattered across codebase
   - **Action**: Update prompt to say "MANDATORY: Run scan_manual_serde.py"

5. **type-ignore-suppressions** → grep `# type: ignore`
   - **Why mandatory**: Surfaces every type suppression - forces review of each one
   - **Prevents**: Agent missing suppressions buried in long files
   - **Action**: Update prompt to say "MANDATORY: Run grep to find ALL type ignore comments"

6. **pydantic-antipatterns** → grep union types + isinstance
   - **Why mandatory**: Surfaces every union mixing BaseModel with weak types, every isinstance check
   - **Prevents**: Agent missing Pydantic type system defeats scattered across codebase
   - **Action**: Already updated - MANDATORY grep patterns in Detection Strategy

### ⚠️ RECOMMENDED Scans (7) - Should suggest but not require

These scans help find candidates faster but don't prevent lazy analysis (agent would likely search anyway):

- **trivial-forwarders**: Grep + AST surfaces candidates - saves time but not essential
- **walrus-get-pattern**: Grep finds `dict.get()` patterns - helpful shortcut
- **timestamp-naming**: Grep finds `_ts` fields - faster than manual search
- **test-assertions**: Grep finds assert patterns - common cases
- **asyncio-antipatterns**: Grep finds asyncio API usage - specific patterns
- **stringly-typed**: AST counter + grep helps prioritize - guidance only
- **suspicious-nullability**: Grep + AST surfaces None usage - analysis aid

**Key characteristic**: Agent would search for these anyway; tool just makes it faster.

**Action**: Update prompts to say "RECOMMENDED (but not required): Run [tool/grep pattern]"

### ✅ OPTIONAL Scans (18) - Correctly treat automation as hints

These patterns require subjective judgment where scanning doesn't prevent lazy analysis:

- All manual review prompts (architectural decisions, style preferences, naming conventions)
- Patterns requiring deep context or domain knowledge
- Quality judgments that can't be batched (each instance needs individual analysis)

**Key characteristic**: Scan doesn't surface concrete candidates that force review; agent must read code and judge each case individually.

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
