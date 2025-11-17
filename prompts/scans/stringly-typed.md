### Automated Detection Strategies

For large codebases, use AST analysis to find candidates (high recall, manual verification needed):

**1. Extract and count string literal repetitions:**
```python
import ast
from collections import Counter
from pathlib import Path

def find_repeated_string_literals(root_dir: Path, min_count: int = 3):
    """Find string literals that appear multiple times (enum candidates)."""
    literals = []

    for py_file in root_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    # Filter short strings and common patterns
                    if 3 <= len(node.value) <= 30 and node.value.replace("_", "").isalnum():
                        literals.append(node.value)
        except SyntaxError:
            continue

    # Find strings that appear multiple times
    counts = Counter(literals)
    return {s: count for s, count in counts.most_common() if count >= min_count}

# Usage: Look for strings like "completed", "pending", "error" appearing 5+ times
candidates = find_repeated_string_literals(Path("."), min_count=5)
for literal, count in candidates.items():
    print(f"{literal}: {count} occurrences")
    # Then grep for this specific literal to see usage context
```

**2. Find comparison patterns (high-recall detector):**
```python
import ast

def find_string_comparisons(py_file: Path):
    """Find all string equality comparisons - candidates for enum usage."""
    comparisons = []
    tree = ast.parse(py_file.read_text())

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            # Check if comparing with string literal
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant):
                    if isinstance(comparator.value, str):
                        comparisons.append(comparator.value)

    return comparisons

# Group by common values to find enum candidates
# Example output: {"completed": 12, "pending": 8, "error": 5}
```

**3. Identify categorical field names:**
```python
import ast

def find_categorical_fields(py_file: Path):
    """Find fields with names suggesting categorical values."""
    categorical_patterns = ["status", "type", "kind", "mode", "state", "level"]
    fields = []

    tree = ast.parse(py_file.read_text())
    for node in ast.walk(tree):
        # Pydantic/dataclass field annotations
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            field_name = node.target.id
            if any(pattern in field_name.lower() for pattern in categorical_patterns):
                # Check if annotated as str (should probably be enum)
                if isinstance(node.annotation, ast.Name) and node.annotation.id == "str":
                    fields.append((py_file, field_name))

    return fields

# Usage: Find all "status: str" fields - likely enum candidates
```

**4. Cross-reference existing enums:**
```bash
# Step 1: Extract all enum definitions
rg --type py "class \w+\(.*Enum\):" -A5 > enums.txt

# Step 2: Extract enum values from definitions
# Parse enums.txt to get values like COMPLETED = "completed"

# Step 3: Search for those string values in non-enum contexts
# If Status enum has "completed", search for raw "completed" strings
rg --type py '"completed"' --glob '!**/types.py' --glob '!**/enums.py'
```

**5. Find assignment patterns (preprocessing):**
```bash
# Extract all status-like assignments to analyze
rg --type py "(status|type|kind|mode|state)\s*=\s*\"([^\"]+)\"" -o | sort | uniq -c | sort -rn

# Output shows which values are used most:
#   15 status="pending"
#   12 status="completed"
#    8 type="webhook"
# → Strong signal to create Status and Type enums
```

**Recommended Workflow:**
1. **Automated extraction**: Run AST scripts to find candidates (high recall, expect false positives)
2. **Manual verification**: Review candidates - are these truly categorical? Do they repeat?
3. **Identify groups**: Which string values represent the same concept? (e.g., "completed", "pending", "error" → Status)
4. **Enum creation**: Group related values into enums
5. **Find-and-replace**: Use the specific enum values you created, search for string literals to replace

**Key insight**: Automated tools give you candidates to investigate, not final answers. String literals like "error" or "test" appear everywhere - manual judgment determines if they're enum candidates.
