# Scan: Unnecessary Verbosity

## Context
@../shared-context.md

## Overview

Code that is longer than necessary without improving readability, maintainability, or clarity. The goal is conciseness without sacrificing understanding.

## Core Principle

**Eliminate intermediate variables that don't add clarity.** If a variable is assigned once and used once immediately after, it's likely unnecessary unless it significantly improves readability.

## Pattern 1: Single-Assignment Variables

Variables assigned once and used exactly once in the next statement.

### BAD: Unnecessary intermediate variables

```python
# BAD: Three lines where one suffices
provider = DockerFileProvider(container_files)
collector = FileCollector(provider)
return collector.collect_files()

# BAD: Single-use variable adds no clarity
result = calculate_total(items)
return result

# BAD: Temporary for simple transformation
temp = value.strip()
return temp.lower()

# BAD: Intermediate for constructor argument
config = load_config()
processor = DataProcessor(config)
return processor
```

### GOOD: Direct usage when clear

```python
# GOOD: Single expression, still clear
return FileCollector(DockerFileProvider(container_files)).collect_files()

# GOOD: Direct return
return calculate_total(items)

# GOOD: Chained methods
return value.strip().lower()

# GOOD: Direct construction
return DataProcessor(load_config())
```

### When Intermediate Variables ARE Good

```python
# GOOD: Complex expression needs breakdown
user_permissions = get_user_permissions(user_id)
group_permissions = get_group_permissions(user_groups)
final_permissions = merge_permissions(user_permissions, group_permissions, overrides)
return apply_policy(final_permissions, policy)

# GOOD: Long identifier used multiple times
connection_pool = get_database_connection_pool()
connection_pool.configure(max_size=100)
connection_pool.set_timeout(30)
return connection_pool

# GOOD: Name adds significant semantic meaning
is_eligible_for_discount = (
    customer.is_premium
    and order.total > 100
    and not customer.has_used_discount_this_month
)
if is_eligible_for_discount:
    apply_discount(order)

# GOOD: Breaking up deeply nested expression
base_url = config.get("api", {}).get("endpoints", {}).get("users", {}).get("base")
full_url = f"{base_url}/profile/{user_id}"
return fetch(full_url)
```

## Pattern 2: Verbose Boolean Returns

### BAD: If-else for boolean

```python
# BAD: Unnecessary if-else
def is_valid(self) -> bool:
    if self.value > 0:
        return True
    else:
        return False

# BAD: If with boolean literal
def has_permission(self) -> bool:
    if self.user.is_admin or self.user.id == self.owner_id:
        return True
    return False
```

### GOOD: Direct boolean expression

```python
# GOOD: Direct return
def is_valid(self) -> bool:
    return self.value > 0

# GOOD: Expression is already boolean
def has_permission(self) -> bool:
    return self.user.is_admin or self.user.id == self.owner_id
```

## Pattern 3: Redundant Conditionals

### BAD: Checking what's already guaranteed

```python
# BAD: Redundant None check after walrus
if (result := compute()) is not None:
    if result:  # Redundant - already checked not None
        process(result)

# BAD: Multiple checks for same condition
if user:
    if user:  # Duplicate check
        return user.name

# BAD: Else after return
def get_status(self):
    if self.is_complete:
        return "complete"
    else:  # Unnecessary else
        return "pending"
```

### GOOD: Minimal necessary checks

```python
# GOOD: Combined check
if result := compute():
    process(result)

# GOOD: Single check
if user:
    return user.name

# GOOD: No else needed
def get_status(self):
    if self.is_complete:
        return "complete"
    return "pending"
```

## Pattern 4: Verbose Exception Handling

### BAD: Catch and re-raise

```python
# BAD: Pointless try-except
try:
    result = dangerous_operation()
except Exception:
    raise  # Just re-raising? Don't catch it!

# BAD: Catch to return None
try:
    return get_value()
except KeyError:
    return None
```

### GOOD: Use appropriate patterns

```python
# GOOD: Let exception propagate
result = dangerous_operation()

# GOOD: Use .get() for dicts
return data.get(key)  # Returns None if missing

# GOOD: Only catch if adding context
try:
    return dangerous_operation()
except ValueError as e:
    raise ProcessingError(f"Failed to process {item}") from e
```

## Pattern 5: Verbose Comprehensions

### BAD: Unnecessary intermediate list

```python
# BAD: Two comprehensions where one suffices
temp = [x * 2 for x in items]
result = [y + 1 for y in temp]

# BAD: Loop for simple transformation
result = []
for item in items:
    result.append(item.upper())
```

### GOOD: Single comprehension

```python
# GOOD: Combined transformation
result = [x * 2 + 1 for x in items]

# GOOD: Comprehension
result = [item.upper() for item in items]
```

## Pattern 6: Walrus Operator Opportunities

The walrus operator (`:=`) can eliminate unnecessary intermediate variables when assigning and immediately checking/using a value.

### BAD: Assign-then-check

```python
# BAD: Two lines for assign + check
result = expensive_call()
if result:
    process(result)

# BAD: Assign + check in while loop
line = file.readline()
while line:
    process(line)
    line = file.readline()

# BAD: Assign + check + access
match = pattern.search(text)
if match:
    return match.group(1)

# BAD: Nested assign + check
data = fetch_data()
if data:
    value = data.get('key')
    if value:
        return value
```

### GOOD: Walrus operator

```python
# GOOD: Assign and check in one line
if result := expensive_call():
    process(result)

# GOOD: Assign in while condition
while line := file.readline():
    process(line)

# GOOD: Assign in conditional
if match := pattern.search(text):
    return match.group(1)

# GOOD: Nested walrus
if (data := fetch_data()) and (value := data.get('key')):
    return value
```

### When NOT to use walrus

```python
# BAD: Sacrifices readability for terseness
if (x := compute_long_complex_name_that_explains_what_it_is()) > 0:
    process(x)  # What was x again?

# BETTER: Name adds clarity
result_from_expensive_validation = compute_long_complex_name_that_explains_what_it_is()
if result_from_expensive_validation > 0:
    process(result_from_expensive_validation)

# BAD: Complex expression in walrus
if (result := (transform(data) if validate(data) else fallback())) is not None:
    ...  # Too complex

# BETTER: Break it down
result = transform(data) if validate(data) else fallback()
if result is not None:
    ...
```

## Detection Strategy

**Primary Method**: Manual code reading - read through source files, understand the context, look for verbose patterns. Automated tools find candidates but miss context.

**Automated Preprocessing** (high recall, requires manual verification):

### Walrus Operator Detector

```python
import ast

class WalrusOpportunityDetector(ast.NodeVisitor):
    """Find assign-then-check patterns that could use walrus operator."""

    def __init__(self):
        self.candidates = []

    def visit_FunctionDef(self, node):
        """Check function body for assign-then-if patterns."""
        for i in range(len(node.body) - 1):
            current = node.body[i]
            next_stmt = node.body[i + 1]

            # Pattern: var = expr; if var:
            if isinstance(current, ast.Assign) and isinstance(next_stmt, ast.If):
                if len(current.targets) == 1 and isinstance(current.targets[0], ast.Name):
                    var_name = current.targets[0].id
                    # Check if condition uses the assigned variable
                    if self._references_var(next_stmt.test, var_name):
                        self.candidates.append({
                            'line': current.lineno,
                            'variable': var_name,
                            'pattern': 'assign-then-if'
                        })

            # Pattern: var = file.readline(); while var:
            if isinstance(current, ast.Assign) and isinstance(next_stmt, ast.While):
                if len(current.targets) == 1 and isinstance(current.targets[0], ast.Name):
                    var_name = current.targets[0].id
                    if self._references_var(next_stmt.test, var_name):
                        self.candidates.append({
                            'line': current.lineno,
                            'variable': var_name,
                            'pattern': 'assign-then-while'
                        })

        self.generic_visit(node)

    def _references_var(self, node, var_name):
        """Check if node references the given variable."""
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id == var_name:
                return True
        return False

# Usage:
# detector = WalrusOpportunityDetector()
# detector.visit(ast.parse(source_code))
# for candidate in detector.candidates:
#     print(f"Line {candidate['line']}: {candidate['variable']} - {candidate['pattern']}")
```

### Boolean Return Detector

```python
import ast

class VerboseBooleanDetector(ast.NodeVisitor):
    """Find if-true-else-false patterns."""

    def visit_FunctionDef(self, node):
        """Check for verbose boolean returns."""
        if len(node.body) == 1 and isinstance(node.body[0], ast.If):
            if_node = node.body[0]
            # Check for: if cond: return True; else: return False
            if (len(if_node.body) == 1 and isinstance(if_node.body[0], ast.Return) and
                len(if_node.orelse) == 1 and isinstance(if_node.orelse[0], ast.Return)):

                if_ret = if_node.body[0].value
                else_ret = if_node.orelse[0].value

                # Check if returning boolean literals
                if (isinstance(if_ret, ast.Constant) and isinstance(else_ret, ast.Constant)):
                    if if_ret.value is True and else_ret.value is False:
                        print(f"Line {if_node.lineno}: Verbose boolean in {node.name}")

        self.generic_visit(node)
```

### Grep Patterns (High-Recall Quick Scan)

```bash
# Pattern: assign-then-check (walrus opportunity)
# Find: var = ...; if var:
rg --type py -U "(\w+)\s*=\s*[^\n]+\n\s*if\s+\1[:\s]" --multiline

# Find: var = ...; while var:
rg --type py -U "(\w+)\s*=\s*[^\n]+\n\s*while\s+\1[:\s]" --multiline

# Pattern: if-true-else-false
rg --type py "if.*:\s*return True\s*(else:\s*return False|return False)" --multiline

# Pattern: else-after-return
rg --type py "return [^\n]+\n\s*else:" --multiline

# Pattern: try-except-raise
rg --type py "except[^:]*:\s*raise\s*$" --multiline

# Pattern: simple for-append (use comprehension)
rg --type py "^\s*for\s+\w+\s+in.*:\s*$" -A1 --multiline | rg "append\("

# Pattern: return-var on next line
rg --type py "(\w+)\s*=\s*[^\n]+\n\s*return\s+\1\s*$" --multiline
```

### Statistical Analysis (Preprocessing)

```bash
# Count lines between variable assignment and usage
# High frequency of adjacent lines suggests single-use pattern
python3 << 'PYTHON'
import ast
import sys
from collections import Counter

distances = Counter()

class DistanceAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.last_assign = {}

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.last_assign[target.id] = node.lineno
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.last_assign:
            distance = node.lineno - self.last_assign[node.id]
            distances[distance] += 1

for file in sys.stdin:
    try:
        tree = ast.parse(open(file.strip()).read())
        analyzer = DistanceAnalyzer()
        analyzer.visit(tree)
    except: pass

# Show distribution - distance=1 is assign-then-immediate-use
for dist in sorted(distances.keys())[:10]:
    print(f"Distance {dist}: {distances[dist]} occurrences")
PYTHON
```

**Critical**: These patterns have false positives. Always read the actual code, understand intent, check if simplification makes sense.

## Context Analysis

**When to keep intermediate variables:**

1. **Complex expressions** - Breaking down improves readability
   - More than 2 levels of nesting
   - More than 60 characters in expression
   - Multiple function calls with unclear purpose

2. **Multiple uses** - Variable used more than once

3. **Debugging/logging** - Variable captured for inspection
   ```python
   result = expensive_computation()
   logger.debug(f"Computation result: {result}")
   return result
   ```

4. **Semantic naming** - Variable name adds significant meaning
   ```python
   # Name explains what the complex expression means
   is_business_day = weekday < 5 and date not in holidays
   ```

5. **Type narrowing** - Helps type checker
   ```python
   user = get_current_user()  # Type narrowed from Optional[User] to User
   if user:
       return user.name  # Type checker knows user is not None
   ```

**When to remove intermediate variables:**

1. **Single assignment + single use** on consecutive lines
2. **Simple transformation** (method call, constructor)
3. **Name adds no semantic value** (e.g., `result`, `temp`, `value`)
4. **Expression is already clear** without the variable

## Fix Strategy

1. **Identify single-use variables** using AST analysis
2. **Check if removal improves or maintains readability**:
   - Is the expression simple? → Remove
   - Does the variable name add meaning? → Keep
   - Would the line become too long (>88 chars)? → Keep
3. **Inline the variable** and remove the assignment
4. **Run tests** to ensure behavior unchanged

## When Verbosity Is Acceptable

- **PEP 8 line length** - Breaking up long expressions
- **Type narrowing** - Helping mypy understand types
- **Debugging** - Keeping variables for inspection
- **Code review** - Explicit steps for clarity
- **Performance** - Avoiding repeated expensive calls

## Benefits

✅ **Fewer lines** - Less code to read and maintain
✅ **Clearer intent** - Direct expression of what's happening
✅ **Reduced noise** - Fewer meaningless variable names
✅ **Better signal-to-noise** - Code that matters stands out

## References

- [PEP 8 - Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)
- [Refactoring: Inline Variable](https://refactoring.com/catalog/inlineVariable.html)
- [Python AST Documentation](https://docs.python.org/3/library/ast.html)
