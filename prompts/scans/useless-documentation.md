# Scan: Useless Documentation

## Context
@../shared-context.md

## Pattern Description

Documentation that merely repeats what is already obvious from function names, parameter names, and type annotations. Good documentation adds information that isn't immediately obvious from reading the code.

## Examples of Useless Documentation

### Javadoc-Style Redundancy

```python
# BAD: Everything is obvious from signature
def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text to max_length with optional suffix.

    Args:
        text: The text to truncate
        max_length: Maximum length of the text
        suffix: The suffix to add (default: "...")

    Returns:
        The truncated text string
    """
    ...

# GOOD: Only document non-obvious behavior
def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """Suffix length counts against max_length."""
    ...
```

### Obvious Getters/Setters

```python
# BAD: Function name says it all
def get_response_id(response: Response) -> str:
    """Get the response ID from a Response object.

    Args:
        response: The Response object

    Returns:
        The response ID as a string
    """
    return response.id

# GOOD: No docstring needed, or minimal
def get_response_id(response: Response) -> str:
    return response.id
```

### Repeating Type Annotations

```python
# BAD: Types already say everything
def parse_response(data: dict[str, Any]) -> Response:
    """Parse response data into a Response object.

    Args:
        data: Dictionary containing response data

    Returns:
        Response: A Response object parsed from the data
    """
    return Response.model_validate(data)

# GOOD: Only document exception behavior
def parse_response(data: dict[str, Any]) -> Response:
    """Raises ValidationError if data doesn't match Response schema."""
    return Response.model_validate(data)
```

### Useless Inline Comments

Comments that just restate what the code obviously does:

```python
# BAD: Comment just repeats the code
# Create grading context
context = GradingContext(rollout=rollout, task=task, environment=environment)

# BAD: Obvious from the code
# Loop through items
for item in items:
    process(item)

# BAD: States the obvious
# Set counter to zero
counter = 0

# BAD: Repeats what assignment does
# Assign result to variable
result = compute_value()

# GOOD: Explains WHY, not WHAT
# GradingContext needs environment for sandbox isolation
context = GradingContext(rollout=rollout, task=task, environment=environment)

# GOOD: Explains non-obvious behavior
# Process in reverse - newest items may invalidate older ones
for item in reversed(items):
    process(item)

# GOOD: Explains pitfall
# Must initialize before calling setup() or it will use default config
counter = 0

# GOOD: No comment needed - code is self-explanatory
result = compute_value()
```

**What makes inline comments useful:**
- **Why** something is done (not what)
- **Pitfalls** or gotchas to avoid
- **Non-obvious requirements** (e.g., "must be called before X")
- **Section summaries** in complex functions
- **Workarounds** for bugs or limitations
- **TODO/FIXME** with context

**What makes inline comments useless:**
- Restating what the code obviously does
- Describing basic language features (`# Create variable`)
- Repeating variable/function names
- Stating `x = y + z` assigns `y + z` to `x`

## What Makes Documentation Useful

Good documentation tells you:
- **Non-obvious behavior**: Side effects, mutation, caching
- **Error conditions**: When exceptions are raised, edge cases
- **Performance implications**: O(n²) behavior, blocking I/O
- **Business logic**: Why something is done, not what is done
- **Assumptions**: Preconditions, invariants
- **Examples**: Complex usage patterns

```python
# GOOD: Explains non-obvious behavior
def truncate_files_by_tokens(files: list[FileInfo], max_tokens: int) -> list[FileInfo]:
    """Greedy truncation: includes whole files first (largest to smallest),
    then binary-search truncates remainder. Stops early if budget < 1000 tokens."""
    ...

# GOOD: Documents exception
def first_assistant_text(response: ResponsesResult) -> str:
    """Raises ValueError if no assistant text found."""
    ...

# GOOD: Explains "why"
def skip_global_compinit() -> None:
    """Skip system compinit to avoid slowdown from oh-my-zsh plugin loading."""
    ...
```

## Detection Strategy

### Grep Patterns

**Docstrings:**
```bash
# Find Args: sections (often indicates javadoc style)
rg --type py '""".*\n.*Args:'

# Find Returns: sections that just repeat return type
rg --type py -A2 'Returns:\s*$'

# Find parameter docs that just repeat param name
rg --type py '    \w+: The \w+'
```

**Inline Comments:**

Useless inline comments are hard to detect with simple grep patterns - it requires semantic analysis. Look for:

**Manual review heuristics:**
1. Comment is nearly identical to next line's variable/function names
   - `# Create grading context` → `context = GradingContext(...)`
   - `# Initialize counter` → `counter = 0`

2. Comment just describes language constructs
   - `# Loop through items` → `for item in items:`
   - `# Return result` → `return result`

3. Comment restates assignment without explaining WHY
   - `# Get configuration` → `config = load_config()`

**What NOT to flag:**
- Section summaries: `# Handle different grading types`
- Explaining purpose: `# Check if it's a date-only value (no time component)`
- Non-obvious requirements: `# Must be called before setup() to avoid race`
- Workarounds: `# Skip global compinit to avoid slowdown`

**Simple patterns that might help (high false positive rate):**
```bash
# Very specific: literal variable name repetition
# "# Create X" right before "X = ..."
# This requires contextual matching - hard to grep reliably
```

### AST + Docstring Analysis

```python
import ast
import re

class UselessDocstringDetector(ast.NodeVisitor):
    def visit_FunctionDef(self, node):
        docstring = ast.get_docstring(node)
        if not docstring:
            return

        # Check for javadoc markers
        if re.search(r'\b(Args|Arguments|Parameters|Returns|Return):', docstring):
            # Analyze if parameters just repeat names
            params = {arg.arg for arg in node.args.args}
            for param in params:
                # Check for "param: The param" pattern
                if re.search(rf'{param}:.*\bThe {param}\b', docstring, re.IGNORECASE):
                    print(f"Useless param doc in {node.name}: {param}")
```

### Heuristics

- **Long Args section**: If every parameter has a doc that's just "The <param>"
- **Returns mirrors type**: If "Returns: str" when return type is `-> str`
- **Function name repetition**: Docstring first sentence just rephrases function name
- **No exception info**: Doc doesn't mention raises/errors but function can raise

## Fix Strategy

**Docstrings:**
1. **Delete obvious docs**: Remove Args/Returns that add no information
2. **Keep useful info**: Preserve exception documentation, non-obvious behavior
3. **Refactor to single line**: If only one useful sentence, make it a single-line docstring
4. **Module-level docs**: Move general explanations to module docstrings

**Inline Comments:**
1. **Delete restatements**: Remove comments that just describe what code does
2. **Ask "why not what"**: If comment doesn't explain why, delete it
3. **Keep explanations**: Preserve comments explaining pitfalls, requirements, workarounds
4. **Improve if salvageable**: Turn "# Create X" into "# X needed for Y" if there's a reason

### Before/After Examples

**Docstrings:**

```python
# Before:
def all_assistant_text(response: ResponsesResult) -> list[str]:
    """Extract all assistant message texts from response.output.

    Args:
        response: ResponsesResult from API call

    Returns:
        List of all assistant texts (may be empty)
    """
    ...

# After:
def all_assistant_text(response: ResponsesResult) -> list[str]:
    ...  # No docstring needed - name and types say it all
```

```python
# Before:
def concatenate_assistant_text(response: ResponsesResult, separator: str = "\n\n") -> str:
    """Extract and concatenate all assistant texts with separator.

    Args:
        response: ResponsesResult from API call
        separator: String to join multiple texts (default: double newline)

    Returns:
        Concatenated assistant text (empty string if none found)
    """
    ...

# After:
def concatenate_assistant_text(response: ResponsesResult, separator: str = "\n\n") -> str:
    ...  # Or minimal: """Returns empty string if no assistant text found."""
```

**Inline Comments:**

```python
# Before:
# Create grading context
context = GradingContext(rollout=rollout, task=task, environment=environment)

# After:
context = GradingContext(rollout=rollout, task=task, environment=environment)
```

```python
# Before:
# Initialize counter
counter = 0

# Loop through items
for item in items:
    # Increment counter
    counter += 1

# After:
counter = 0
for item in items:
    counter += 1
```

```python
# Before:
# Get configuration
config = load_config()
# Create processor with config
processor = DataProcessor(config)
# Process the data
result = processor.process(data)

# After:
config = load_config()
processor = DataProcessor(config)
result = processor.process(data)

# Or even better (from unnecessary-verbosity scan):
result = DataProcessor(load_config()).process(data)
```

## False Positives (Keep These)

- **Public API documentation**: If it's a library, users need docs
- **Complex algorithms**: Non-obvious implementation approach
- **Domain-specific logic**: Business rules that aren't obvious from code
- **Type variance**: When generic types need explanation
- **Module-level context**: Overview of what module provides

## Validation

```bash
# Count reduction in documentation
git diff --stat

# Ensure no actual information was lost
git diff | grep -A5 -B5 '"""'

# Verify code still makes sense
git show HEAD | rg -A10 "^-.*def "
```

## References

- Python PEP 257 (Docstring Conventions)
- Google Python Style Guide (focus on "what's not obvious")
- When to document: https://stackoverflow.blog/2021/12/23/best-practices-for-writing-code-comments/
