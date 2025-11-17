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

## Detection Strategy

### AST-Based Detection (Recommended)

Use AST analysis to find single-assignment variables:

```python
import ast
from collections import defaultdict

class SingleAssignmentDetector(ast.NodeVisitor):
    def __init__(self):
        self.assignments = defaultdict(list)  # name -> [line numbers]
        self.usages = defaultdict(list)       # name -> [line numbers]

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.assignments[target.id].append(node.lineno)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.usages[node.id].append(node.lineno)
        self.generic_visit(node)

    def find_single_use_vars(self):
        """Find variables assigned once and used once immediately after."""
        candidates = []
        for name, assign_lines in self.assignments.items():
            if len(assign_lines) == 1 and name in self.usages:
                use_lines = self.usages[name]
                if len(use_lines) == 1 and use_lines[0] == assign_lines[0] + 1:
                    candidates.append((name, assign_lines[0]))
        return candidates
```

### Grep Patterns (Quick Scan)

```bash
# Find 'return variable' pattern (potential single-use)
rg --type py -A1 "^\s*(\w+) = " | rg "return \1$"

# Find if-true-else-false pattern
rg --type py "if.*:\s*return True\s*else:\s*return False" --multiline

# Find else-after-return
rg --type py "return .+\n\s*else:" -A1

# Find try-except-raise pattern
rg --type py "except.*:\s*raise$" --multiline

# Find simple for-append pattern
rg --type py "for .* in .*:\s*\w+\.append\(" -A1
```

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
