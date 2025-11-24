# Scan: Useless Comments and Documentation

## Context
@../shared-context.md

## Core Principle

**Comments and documentation should add value beyond what the code itself expresses.** This applies to:
- Inline comments (`# ...`)
- Block comments (`# ---- Section ----`)
- Docstrings (`"""..."""`)
- Type hints and annotations (should be accurate, not duplicated in docs)

A comment or docstring is useless if it:
- Duplicates information already clear from code structure (types, decorators, names)
- States the obvious ("increment counter" for `counter += 1`, "Validate config" for `validate_config()`)
- Is outdated or contradicts the code
- Uses vague language that doesn't clarify anything

**Good documentation explains WHY, not WHAT.** The code already shows what it does.

## Overview

Python code should be self-documenting through clear naming and structure. Documentation is valuable only when it provides context, rationale, or non-obvious information that cannot be expressed in code.

This scan targets both **comments** and **docstrings** - the same principles apply to both.

---

## Antipattern 1: Duplicating Code Semantics

### BAD: Comment repeats what decorators/types already say

```python
# BAD: Everything in comment is already expressed by code
# Tool: container exec (flat MCP payload, validated via ExecInput)
@mcp.tool(name="exec", flat=True)
async def tool_exec(input: ExecInput, ctx: Context) -> BaseExecResult:
    #              ^^^^^^ type annotation ^^^^  ^^^^^^ return type
    #  ^^^^^^^^ decorator already says it's a tool
    #                     ^^^^ decorator already says flat=True
    """Run a shell command inside the per-session Docker container."""
    ...

# BAD: Comment just restates the type annotation
def process_user(user: User):  # user is a User object
    ...

# BAD: Docstring duplicates function name
def validate_config(config: Config) -> bool:
    """Validate config."""  # Useless! Function name already says this
    ...

# BAD: Docstring duplicates parameter types
def process_user(user: User, admin: bool = False) -> None:
    """Process user.

    Args:
        user: User object to process
        admin: Boolean flag for admin privileges
    """
    # Type annotations already document types! Docs should explain semantics, not types
    ...
```

### GOOD: Comment adds non-obvious context

```python
# GOOD: Explains WHY we use flat=True (not obvious from decorator alone)
@mcp.tool(name="exec", flat=True)  # flat=True exposes ExecInput fields directly to MCP clients
async def tool_exec(input: ExecInput, ctx: Context) -> BaseExecResult:
    """Run a shell command inside the per-session Docker container.

    Uses docker exec for session containers, or ephemeral containers for
    one-off execution. Ephemeral mode avoids state pollution between runs.
    """
    ...

# GOOD: Docstring explains non-obvious validation logic and cross-field constraints
def validate_config(config: Config) -> bool:
    """Validate config structure and cross-field constraints.

    Returns False if optimizer_type="adam" but adam_beta1 is missing,
    or if learning_rate is negative. See docs/config-schema.md for full rules.
    """
    ...

# GOOD: Fix the names first, then docs only for non-obvious details
def update_user_last_seen(user: User, *, from_admin_console: bool = False) -> None:
    """Update last_seen timestamp and log access (with optional admin audit trail).

    Raises SessionExpiredError if user.session has expired.
    """
    # Function name says WHAT it does, param name captures semantic context
    # (why it matters - admin requests get special handling: skip rate limit, audit log)
    # Docs cover edge cases (SessionExpiredError) rather than repeating what code says
    ...
```

---

## Antipattern 2: Obvious Statements

### BAD: Comment states what code already shows

```python
# BAD: Obvious from code
# Increment counter
counter += 1

# BAD: Obvious from variable names
# Get user ID from request
user_id = request.user_id

# BAD: Obvious from control flow
# Check if user exists
if user is not None:
    ...

# BAD: Obvious from function/method names
# Close the client
await client.close()

# BAD: Section header that adds no value
# ---- Helper functions ----
def helper1():
    ...
```

### GOOD: Comment explains non-obvious reasoning

```python
# GOOD: Explains WHY we increment (not obvious)
counter += 1  # Track retries; will abort after 3 (see MAX_RETRIES)

# GOOD: Explains edge case handling
user_id = request.user_id or request.session.get("impersonated_user_id")
# Fall back to session when admin is impersonating another user

# GOOD: Explains why check is necessary
if user is not None:
    # Defensive: user can be None during initial OAuth flow before profile sync
    await user.update_last_seen()

# GOOD: Explains cleanup timing
await client.close()
# Must close before exiting context to flush pending writes to disk
```

---

## Antipattern 3: Outdated or Wrong Comments

### BAD: Comment contradicts code (stale)

```python
# BAD: Comment says "retry 3 times" but code retries 5 times
# Retry up to 3 times on network errors
for attempt in range(5):
    ...

# BAD: Comment references old parameter name
def process_request(request: Request):  # process the req object
    #                         ^^^^^^^ parameter is 'request', not 'req'
    ...

# BAD: TODO that was already done
# TODO: Add validation for email format
def validate_email(email: str) -> bool:
    # Validation logic here (already implemented!)
    return EMAIL_REGEX.match(email) is not None
```

### GOOD: Keep comments in sync or remove them

```python
# GOOD: Accurate comment
# Retry up to 5 times with exponential backoff
for attempt in range(5):
    ...

# GOOD: No misleading comment needed
def process_request(request: Request):
    # Type annotation already documents the parameter
    ...

# GOOD: Remove completed TODOs entirely
def validate_email(email: str) -> bool:
    return EMAIL_REGEX.match(email) is not None
```

---

## Antipattern 4: Vague Comments

### BAD: Comment doesn't clarify anything

```python
# BAD: "Handle the data" - how? why?
# Handle the data
result = transform(data)

# BAD: "Important!" - what's important? why?
# Important!
if config.mode == "production":
    ...

# BAD: "HACK" without explanation
# HACK
time.sleep(0.1)

# BAD: "Fix this" without context
# Fix this later
return None
```

### GOOD: Specific, actionable comments

```python
# GOOD: Explains what transformation and why
# Convert from OpenAI format to internal format (loses reasoning tokens, see #123)
result = transform(data)

# GOOD: Explains why production mode is special
# Production mode disables debug logging and uses encrypted credentials
if config.mode == "production":
    ...

# GOOD: Explains why the hack is necessary
# Workaround for race condition in upstream library (see issue #456)
# Remove when we upgrade to v2.0+ which includes the fix
time.sleep(0.1)

# GOOD: Explains what needs fixing and why
# TODO: Return proper error instead of None (requires client update to handle errors)
return None
```

---

## When Comments ARE Valuable

### ✓ Explaining non-obvious algorithms

```python
# Binary search requires sorted input; we sort once here rather than per-query
data.sort(key=lambda x: x.timestamp)
```

### ✓ Documenting edge cases

```python
# Empty list is valid (represents "no filters"), but None means "use defaults"
if filters is None:
    filters = DEFAULT_FILTERS
```

### ✓ Referencing external context

```python
# Matches OpenAI API behavior: trailing newlines are stripped (see docs/api.md#text-normalization)
return text.rstrip('\n')
```

### ✓ Warning about gotchas

```python
# WARNING: Modifies input list in-place for performance (avoids copy)
def deduplicate(items: list) -> list:
    ...
```

### ✓ Explaining temporary workarounds

```python
# Temporary: remove this when upstream PR #789 is merged and we upgrade
if isinstance(response, LegacyFormat):
    response = convert_to_new_format(response)
```

### ✓ Documenting WHY, not WHAT

```python
# Use thread pool instead of process pool because:
# 1. Data is already in memory (no serialization overhead)
# 2. Tasks are I/O-bound (network calls), not CPU-bound
with ThreadPoolExecutor() as executor:
    ...
```

---

## Detection Strategy

**MANDATORY first step**: Run `scan_comments.py` and process ALL output.

- This scan is **required** - do not skip this step
- You **must** read and handle the complete scan output (can pipe to temp file)
- Do not sample or skip any results - process every comment/docstring found
- Prevents lazy analysis by forcing examination of all comments in the codebase

**Goal**: Find ALL useless comments for manual review (100% recall target).

**Approach**: Low-precision, high-recall extraction of ALL comments, then manual filtering.

### Automated Scanning Tool

**Tool**: `prompts/scans/scan_comments.py` - AST-based scanner for all comments and docstrings

**What it finds**:
- **All comments**: Inline (`x = 1  # comment`), block (`# comment`), docstrings
- **Context**: 3 lines before and after each comment
- **Type classification**: Distinguishes inline/block/docstring

**Usage**:
```bash
# Run on entire codebase
python prompts/scans/scan_comments.py . > comments_scan.json

# Run on specific directory
python prompts/scans/scan_comments.py path/to/module > module_comments.json

# Pretty-print summary
python prompts/scans/scan_comments.py . 2>&1 | grep "===" -A 10
```

**Output structure**:
- `summary`: Counts of comments and files
- `comments`: Dict mapping file paths to lists of `{line, comment, context_before, context_after, type}`

**Tool characteristics**:
- **100% recall**: Finds ALL comments and docstrings in valid Python files
- **No filtering**: Tool surfaces raw data; you do filtering for "useless"
- **Context included**: 3 lines before/after for manual review

### Filtering Heuristics (For Your Review)

These patterns can guide your filtering of scan results. Apply these heuristics during manual review.

**High-confidence useless patterns**:
- Duplicating type annotations: "user is a User object" when signature shows `user: User`
- Obvious operations: "increment counter" for `counter += 1`
- Section headers with no semantic value: `# ---- Helper functions ----`
- Empty TODOs: `# TODO:` with no description

**High-confidence useful patterns**:
- Explains WHY: Contains "why", "because", "reason"
- Documents workarounds: Contains "workaround", "temporary", "hack"
- References context: "see issue #123", "per docs at..."
- Edge cases/warnings: "edge case", "warning", "gotcha"
- TODOs with context: "TODO(alice): refactor after v2.0"

**Verification approach**:
1. Load scan results with comments + context
2. For each comment, check:
   - Does it duplicate information from code structure (types, names, decorators)?
   - Does it explain WHY, not just WHAT?
   - Is it accurate (check context_after against comment)?
   - Could better naming/refactoring eliminate need for comment?
3. Categorize: USELESS (remove), VAGUE (clarify or remove), USEFUL (keep)

### Automated Scan Commands

```bash
# Find all comments (including inline comments)
rg --type py '^[^#]*#' --line-number

# Find block comments (lines starting with #)
rg --type py '^\s*#' --line-number

# Find TODO comments
rg --type py '\bTODO\b' --line-number --ignore-case

# Find comments that might duplicate type annotations
rg --type py '#.*\b(is a|is an|type of|instance of)\b' --line-number --ignore-case

# Find section header comments
rg --type py '^\s*#\s*-+.*-+\s*$' --line-number
```

### Manual Review Process (Required)

Since this is a low-precision scan, **manual review is mandatory**:

1. **Extract ALL comments** with ±3 line context (using script above)
2. **Review each comment** in context:
   - Does it add information beyond code structure?
   - Does it explain WHY, not just WHAT?
   - Is it accurate and up-to-date?
   - Could it be replaced by better naming/refactoring?
3. **Categorize**:
   - USELESS: Remove entirely
   - OUTDATED: Update or remove
   - VAGUE: Make specific or remove
   - USEFUL: Keep (explains WHY, edge cases, non-obvious behavior)
4. **Refactor** before removing:
   - If comment explains unclear code, improve the code first
   - Extract magic numbers to named constants
   - Rename variables to be self-documenting

---

## Fix Strategy

### Priority 1: Remove Duplicates

```python
# Before
# Tool: container exec (flat MCP payload, validated via ExecInput)
@mcp.tool(name="exec", flat=True)
async def tool_exec(input: ExecInput, ctx: Context) -> BaseExecResult:
    ...

# After - decorator and types speak for themselves
@mcp.tool(name="exec", flat=True)
async def tool_exec(input: ExecInput, ctx: Context) -> BaseExecResult:
    """Run a shell command inside the per-session Docker container."""
    ...
```

### Priority 2: Update Outdated Comments

```python
# Before - WRONG
# Retry up to 3 times on network errors
for attempt in range(5):
    ...

# After - CORRECTED
# Retry up to 5 times on network errors
for attempt in range(5):
    ...
```

### Priority 3: Make Vague Comments Specific

```python
# Before - VAGUE
# Handle the data
result = transform(data)

# After - SPECIFIC
# Convert from OpenAI response format to internal BaseExecResult format
result = transform(data)
```

### Priority 4: Remove Obvious Statements

```python
# Before
# Increment counter
counter += 1

# After - no comment needed
counter += 1
```

---

## Output Format for Manual Review

Generate a review document with all comments:

```markdown
# Comment Review: <file_path>

## Line <N>: [<type>] <comment_preview>

**Comment:**
```
<full_comment_text>
```

**Context Before:**
```python
<3_lines_before>
```

**Context After:**
```python
<3_lines_after>
```

**Assessment:** [USELESS | OUTDATED | VAGUE | USEFUL | UNCLEAR]

**Action:** [REMOVE | UPDATE | CLARIFY | KEEP]

**Reasoning:** <why_this_assessment>

---
```

---

## Recall/Precision Estimates

- **Automated extraction**: 100% recall (finds all comments)
- **Automated filtering**: ~20% precision, ~60% recall
  - Low precision: many false positives (useful comments flagged as useless)
  - Medium recall: misses contextual uselessness (comment is technically accurate but redundant)
- **Manual review required**: Target 100% recall through reading every comment in context

---

## Benefits

✅ **Cleaner code** - Less noise, easier to read
✅ **No misleading info** - Removes outdated/wrong comments
✅ **Self-documenting** - Forces better naming and structure
✅ **Maintainability** - No comment drift when code changes
✅ **Focus on value** - Remaining comments are truly helpful

---

## Examples from Codebase

### Duplicating Decorator Semantics

```python
# ✗ BEFORE: Comment duplicates decorator + type annotations
# Tool: container exec (flat MCP payload, validated via ExecInput)
@mcp.tool(name="exec", flat=True)
async def tool_exec(input: ExecInput, ctx: Context) -> BaseExecResult:
    """Run a shell command inside the per-session Docker container."""
    ...

# ✓ AFTER: Decorator and types are self-documenting
@mcp.tool(name="exec", flat=True)
async def tool_exec(input: ExecInput, ctx: Context) -> BaseExecResult:
    """Run a shell command inside the per-session Docker container."""
    ...
```

### Obvious Statements

```python
# ✗ BEFORE: Obvious from method name
# Close the client
await client.close()

# ✓ AFTER: Only comment if non-obvious
await client.close()  # Must close before exit to flush pending writes
```

---

## References

- [PEP 8 - Comments](https://peps.python.org/pep-0008/#comments)
- [Google Python Style Guide - Comments and Docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- [Code Complete - Self-Documenting Code](https://www.oreilly.com/library/view/code-complete-2nd/0735619670/)
