# Scan: Functions That Should Be Inlined

## Context
@../shared-context.md

## Pattern Description

Functions that exist purely to forward calls without reducing complexity. These should be inlined at their usage sites.

**Key principle**: Helper functions should exist IFF they make things LESS complex. If usage sites wouldn't be made longer or more complex by inlining the helper's body, the helper shouldn't exist.

## Examples: Should Inline

### BAD: Doesn't reduce complexity

```python
# BAD: Called exactly once, doesn't simplify the call site
def dump_response(value: OpenAIResponse | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return value.model_dump(mode="json")

# Usage (called once):
result = dump_response(snapshot.response)

# BETTER: Inline it - usage site is no more complex
result = snapshot.response.model_dump(mode="json") if snapshot.response else None
```

```python
# BAD: Just forwarding to another module, adds no value
def extract_text_from_openai_response(response: ResponsesResult) -> str:
    return first_assistant_text(response)

# Usage:
text = extract_text_from_openai_response(response)

# BETTER: Inline it - just as clear
from module import first_assistant_text
text = first_assistant_text(response)
```

```python
# BAD: Short body, called twice, doesn't reduce complexity
def get_current_commit(repo: pygit2.Repository) -> pygit2.Oid:
    return repo.head.target

# Usage sites:
current = get_current_commit(repo)
parent = get_current_commit(other_repo)

# BETTER: Inline - usage sites are just as clear
current = repo.head.target
parent = other_repo.head.target
```

## Examples: Keep Function (Legitimate Reasons)

### GOOD: Facade pattern / API design

```python
# GOOD: Provides stable API even if implementation changes
class CacheClient:
    def get(self, key: str) -> dict[str, Any] | None:
        return self._backend.get(key)  # Facade over backend

    def set(self, key: str, value: dict[str, Any]) -> None:
        return self._backend.set(key, value)  # Facade over backend

# Reason: API stability, abstraction, dependency injection point
```

### GOOD: Implements interface or protocol

```python
# GOOD: Implements abstract method from base class
class SQLRepository(Repository):
    def save(self, item: Item) -> None:
        return self._session.add(item)  # Implementing interface

# Reason: Required by interface, even if body is simple
```

### GOOD: Actually reduces complexity

```python
# GOOD: Called 10+ times, consolidates complex pattern
def safe_json_loads(data: str | None) -> dict[str, Any]:
    if data is None:
        return {}
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON: %s", data)
        return {}

# Usage sites (10+ places):
config = safe_json_loads(row.config_json)
metadata = safe_json_loads(row.metadata_json)
...

# Reason: Consolidates error handling logic, used many times
```

### GOOD: Provides backward compatibility during migration

```python
# GOOD: Temporary during migration (document with TODO)
# TODO(2025-12): Remove after all callers migrated to new API
def get_user(user_id: str) -> User:
    return user_service.fetch_user(user_id)

# Reason: Temporary shim during refactoring (should be removed later)
```

## Detection Strategy

**Goal**: Find ALL functions that should be inlined (100% recall target).

**Recall/Precision**: High recall (~90%) with automation, low precision (~20-30%)
- Functions called exactly once: ~95% recall, ~20% precision (many legitimate one-time wrappers)
- Functions with short body (<= 3 lines): ~85% recall, ~25% precision (many valid simple functions)
- Single-return functions: ~90% recall, ~30% precision (facades, interface implementations, etc.)

**Why low precision is expected**:
- Legitimate reasons for simple forwarders: facades, interfaces, API stability, backward compatibility
- Can't tell from syntax alone whether function reduces complexity at call sites
- Need to understand: call count, architectural role, complexity trade-offs

**Recommended approach**:
1. Run high-recall retrievers to gather ALL candidates (~90% recall, ~20-30% precision)
2. For each candidate, analyze:
   - **Call count**: How many times is it called? (vulture, grep, AST)
   - **Complexity**: Would inlining make call sites more complex?
   - **Architecture**: Is this a facade, interface implementation, or API boundary?
   - **Purpose**: Does it consolidate logic or just shuffle calls?
3. Filter out legitimate forwarders (facades, interfaces, backward compat)
4. Inline confirmed trivial forwarders
5. **Supplement with manual reading** to find complex cases automation misses

**High-recall, low-precision retrievers**:

### 1. Functions Called Exactly Once (Especially Same File)

```bash
# Build call count database using AST or grep
# For each function, count references:
# - 1 reference (definition only) → unused (different pattern)
# - 2 references (definition + 1 call) → candidate for inlining
# - Especially if call is in same file

# Grep-based approximation (counts occurrences):
rg --type py "function_name" --count-matches

# Better: Use AST tool to build call graph, flag functions with exactly 1 caller
```

**High precision indicator**: Called once in same file → very likely should be inlined

### 2. Functions with Short, Low-Complexity Body

```bash
# Find functions with <= 3 lines (excluding docstrings)
# AST tool can count statements:
# - 1 statement (single return) → high candidate
# - 2-3 statements (simple logic) → medium candidate
# - No loops, no complex conditionals → higher candidate

# Grep approximation (single-return functions):
rg --type py -U "def \w+\([^)]*\):[^\n]*\n\s+return "

# Find very short functions (likely simple):
rg --type py -A3 "^def " | grep -B1 -A3 "return" | grep -B4 "^--$"
```

### 3. Single-Statement Return Functions

```bash
# Functions with body: single return statement
rg --type py -U "def \w+\([^)]*\):[^\n]*\n\s+return \w+\("
```

### 4. AST-Based Discovery (Comprehensive)

Build tool that analyzes:
```python
# Pseudocode for AST-based detection
for func in all_functions:
    if func.body_lines <= 3:
        call_count = count_calls_to(func.name)
        if call_count == 1:
            yield HighPriorityCandidate(func, reason="called once")
        elif call_count <= 3 and is_simple_body(func):
            yield MediumPriorityCandidate(func, reason="few calls, simple body")

        # Check if it's just forwarding
        if is_single_return_call(func):
            yield Candidate(func, reason="single return call")
```

**Verification for each candidate**:

1. **Check call count**: Functions called 1-2 times are high priority candidates
2. **Check architectural role**:
   - Method overriding abstract method? → Keep (interface requirement)
   - Public method in facade class? → Keep (API design)
   - Private helper with simple body? → Likely inline
3. **Complexity analysis**:
   ```python
   # For each call site:
   # Current: result = helper_func(arg1, arg2)
   # After inline: result = <helper_body with arg1, arg2>
   # Is "After" significantly longer or more complex? If no → inline
   ```
4. **Check for consolidation**:
   - Does function consolidate error handling? → Keep
   - Does function consolidate validation? → Keep
   - Does function just forward? → Inline

## Decision Framework: Inline or Keep?

For each candidate function, ask:

### 1. **Call Count Test**
- Called once in same file? → **Strong inline candidate**
- Called 2-3 times with simple body? → **Medium inline candidate**
- Called 10+ times? → **Check complexity benefit**

### 2. **Complexity Test**
```python
# Simulate inlining at each call site:
# Would this make the call site:
# - Longer? (By how much? 1 line → 3 lines might be fine)
# - More complex? (Nested conditionals, error handling)
# - Less clear? (Complex expression vs named function)

# If call sites become more complex → KEEP function
# If call sites stay same complexity → INLINE
```

### 3. **Architectural Role Test**
- [ ] Implements interface/abstract method? → **KEEP**
- [ ] Part of public API (facade pattern)? → **KEEP**
- [ ] Provides dependency injection point? → **KEEP**
- [ ] Backward compatibility shim? → **KEEP (temporarily)**
- [ ] Private helper, simple body? → **LIKELY INLINE**

### 4. **Consolidation Test**
- Consolidates error handling? → **KEEP**
- Consolidates validation logic? → **KEEP**
- Consolidates complex computation? → **KEEP**
- Just forwards calls? → **INLINE**

## Fix Strategy (When Inlining)

1. **Identify all call sites**:
   ```bash
   rg --type py "function_name\("
   ```

2. **Inline the function body** at each call site:
   ```python
   # Before:
   result = helper_func(arg1, arg2)

   # After (inline function body):
   result = <body of helper_func with arg1, arg2 substituted>
   ```

3. **Remove function definition** after all call sites updated

4. **Update imports** if needed (if helper imported underlying function)

5. **Verify**: Run mypy and tests

## When to Keep (Don't Inline)

These patterns have **legitimate reasons** for simple forwarding:

### Architectural Patterns
- **Facade pattern**: Stable API over changing implementation
- **Interface implementation**: Required by abstract base class
- **Dependency injection**: Provides customization point for testing

### Complexity Reduction
- **Consolidates error handling**: Multiple try/except blocks → single function
- **Consolidates validation**: Complex checks used in multiple places
- **Called many times**: 10+ call sites benefit from centralized logic

### Temporary Patterns
- **Backward compatibility**: During migration/refactoring (document with TODO)
- **API versioning**: Supporting old API during deprecation period

## Complete Example: Inlining Decision

### Candidate: `dump_response`

```python
# Function definition:
def dump_response(value: OpenAIResponse | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return value.model_dump(mode="json")

# Called exactly once:
result = dump_response(snapshot.response)
```

**Decision analysis**:
1. ✅ **Call count**: Called once → strong inline candidate
2. ✅ **Complexity test**:
   - Current: 1 line
   - After inline: 1 line (ternary expression)
   - No increase in complexity
3. ✅ **Architectural role**: Private helper, not interface/facade
4. ✅ **Consolidation test**: Just forwards, no error handling

**Decision**: **INLINE**

**Fix**:
```python
# Before:
from module import dump_response
result = dump_response(snapshot.response)

# After:
result = snapshot.response.model_dump(mode="json") if snapshot.response else None
```

### Counter-Example: `safe_json_loads` (Keep)

```python
# Function definition:
def safe_json_loads(data: str | None) -> dict[str, Any]:
    if data is None:
        return {}
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON: %s", data)
        return {}

# Called 15 times across codebase:
config = safe_json_loads(row.config_json)
metadata = safe_json_loads(row.metadata_json)
...
```

**Decision analysis**:
1. ❌ **Call count**: Called 15 times → check complexity benefit
2. ❌ **Complexity test**:
   - Current: 1 line per call site
   - After inline: 6 lines per call site (try/except block)
   - Significant increase in complexity (×15)
3. ❌ **Consolidation test**: Consolidates error handling logic

**Decision**: **KEEP** - Reduces complexity by consolidating error handling

## Validation

```bash
# After inlining, verify no references remain
rg "function_name\("

# Run type checker
mypy path/to/modified/files.py

# Run tests to ensure behavior unchanged
pytest path/to/tests/
```
