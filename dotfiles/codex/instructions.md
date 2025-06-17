---
title: Code Agent Instructions
---

# Coding Standards

## CRITICAL RULES (NEVER VIOLATE)

1. **NEVER swallow exceptions** - Always handle specific exceptions or crash loudly
2. **NEVER use string concatenation for structured data** (URLs, SQL, HTML, JSON)
3. **NEVER use `getattr`/`setattr`** unless literally no alternative exists
4. **ALWAYS fail fast** - Crash immediately on unexpected state

## Repository Instructions

If the repository has a `README.md`, read it and refer to it.
If there is `CLAUDE.md` or `CODEX.md`, read it and follow it.

## References Folder (if present)

If you see a `references/` folder:
- **DO NOT edit** the reference files inside
- Look for `references/fetch.sh` which fetches/updates references
- Feel free to add to `fetch.sh` for new references

Example `fetch.sh` might include:
```bash
# Fetch API docs and convert to markdown
curl -L https://example.com/api-docs.html | pandoc -f html -t markdown > api.md

# Clone specific files
curl -O https://raw.githubusercontent.com/user/repo/main/implementation.py
```

Only `fetch.sh` is version controlled. Fetched files are gitignored.

# Internet use OK

Feel free to fire HTTP queries for testing, fetching documentation, source code for reference, etc.
*Especially* to add to the `references/` folder.

If useful for testing etc., just fire them right away without asking. Also start servers, experiment, etc.

## One-off Scripts

For temporary/experimental scripts, make their throwaway nature obvious:

**Wrong:** `test_api.py` in repo root
**Right:** `throwaway/2024-01-15/test_api.py` with header `# THROWAWAY SCRIPT - DO NOT REUSE`

# General across languages

## Code Brevity
Minimize code length aggressively. Prefer:
- One-liners over multi-line when readable
- List/dict comprehensions over loops
- Ternary operators over if/else blocks
- Built-in functions over manual implementations

**This is more important than some traditional "clean code" rules.**

```python
# Wrong - unnecessary loop:
operands = []
for op_id in operand_ids:
    if expr := _parse_single_component(store, op_id):
        operands.append(expr)

# Right - list comprehension:
operands = [expr for op_id in operand_ids if (expr := _parse_single_component(store, op_id))]
```

## No Trailing Whitespace

Remove all trailing whitespace. Empty lines should be truly empty.

## DRY (Don't Repeat Yourself)

Be aggressive about eliminating repetition. The longer the repeated pattern, the more important to refactor it. Use whatever abstraction fits: loops, functions, decorators, context managers, etc.

**Example using loops:**
```python
# Wrong:
if category is not None:
    habit_data["category"] = category
if goal_type is not None:
    habit_data["goal_type"] = goal_type
if target_value is not None:
    habit_data["target_value"] = target_value

# Right:
for key, value in {
    "category": category,
    "goal_type": goal_type,
    "target_value": target_value,
}.items():
    if value is not None:
        habit_data[key] = value
```

**Example using mappings:**
```python
# Wrong - repetitive if/elif:
if operator_id == AND_OPERATOR_ID:
    return _parse_boolean_expression(store, "AND", node.children[1:])
elif operator_id == OR_OPERATOR_ID:
    return _parse_boolean_expression(store, "OR", node.children[1:])
elif operator_id == NOT_OPERATOR_ID:
    return _parse_boolean_expression(store, "NOT", node.children[1:])

# Right - use mapping:
OPERATORS = {AND_OPERATOR_ID: "AND", OR_OPERATOR_ID: "OR", NOT_OPERATOR_ID: "NOT"}
if operator_id in OPERATORS:
    return _parse_boolean_expression(store, OPERATORS[operator_id], node.children[1:])
```

### Particular case: No redundant special cases for empty structures

Do not implement redundant special cases for empty lists/dicts/structures if they do not change behavior.

**Wrong** (function formats a list as `<1 2 3>`):
```python
def format_numbers(xs: list[int]):
    if not xs:      # <-- BAD: redundant special case
        return '<>'  # Same result as general case below
   
    result = '<'
    for i, n in enumerate(xs):
        if i > 0:
            result += ' '
        result += str(n)
    result += '>'
    return result
```

The special case `if not xs` is redundant because the loop naturally handles empty lists, producing the same `<>` output.

CORRECTED:

```python
def format_numbers(xs: list[int]):
    result = '<'
    for i, n in enumerate(xs):
        if i > 0:
            result += ' '
        result += str(n)
    result += '>'
    return result
```

## Exception Handling

**FORBIDDEN:**
```python
try:
    risky_operation()
except Exception:  # NEVER do this
    pass  # ABSOLUTELY FORBIDDEN
```

**Wrong:**
```python
try:
    risky_operation()
except Exception as e:  # Too broad
    logger.error(f"Something went wrong: {e}")
```

**Right:**
```python
try:
    risky_operation()
except (ValueError, KeyError) as e:  # Specific exceptions
    logger.error(f"Data validation failed: {e}")
    raise  # Re-raise or handle appropriately
```

Only catch `Exception` at the very outer boundary (e.g., request handlers) and ALWAYS log it.

## Early bail-out

Use early bail-out pattern. Including making functions to enable using it when it makes things nicer.

**Wrong:**
```python
def process_data(data):
    if data is not None and len(data) > 0:
        validate_data(data)
        transformed = transform_data(data)
        result = analyze_data(transformed)
        save_results(result)
        return result
    else:
        logger.error("No data provided")
        raise ValueError("Data cannot be empty")
```

**Right:**
```python
def process_data(data):
    if not data:  # Early bail-out
        logger.error("No data provided")
        raise ValueError("Data cannot be empty")
    
    validate_data(data)
    transformed = transform_data(data)
    result = analyze_data(transformed)
    save_results(result)
    return result
```

DO NOT do:

```python
async def _handle_interfaces_removed(self, path: str, interfaces: list[str]) -> None:
    """Handle interfaces being removed (e.g., adapter disappearing)."""
    if path == self._adapter_path and "org.bluez.Adapter1" in interfaces:
        logger.warning(f"Bluetooth adapter removed: {path}")
        # Clean up adapter
        if self._adapter_properties_iface:
            self._adapter_properties_iface.off_properties_changed(self._handle_adapter_properties_changed)
        self._adapter_path = None
        # ... bunch more code in this branch, nothing outside it ...
```

Instead, DO:

```python
async def _handle_interfaces_removed(self, path: str, interfaces: list[str]) -> None:
    """Handle interfaces being removed (e.g., adapter disappearing)."""
    if path != self._adapter_path or "org.bluez.Adapter1" not in interfaces:
        return  # Early bail-out if not the adapter we're interested in
    logger.warning(f"Bluetooth adapter removed: {path}")
    # Clean up adapter
    if self._adapter_properties_iface:
        self._adapter_properties_iface.off_properties_changed(self._handle_adapter_properties_changed)
    self._adapter_path = None
    ...
```

This just saved us an indentation level.
This can be especially nice in helper functions.

## Document Current State Only

No historical comments like `# This used to work this way but we changed it`. 
Don't keep broken code "for backward compatibility". It was broken. Delete it.

**Avoid redundant docstrings:**
```python
# Wrong - docstring just repeats what's obvious from signature:
def _parse_boolean_expression(store: NodeStore, operator: str, operand_ids: list[NodeId]) -> BooleanSearch | None:
    """
    Parse a boolean expression with the given operator and operands.
    
    Args:
        store: The NodeStore
        operator: The boolean operator ("AND", "OR", "NOT")
        operand_ids: List of operand node IDs
    
    Returns:
        The parsed boolean expression or None
    """
    operands = [expr for op_id in operand_ids if (expr := _parse_single_component(store, op_id))]
    return BooleanSearch(operator, operands) if operands else None

# Right - no docstring, or only document non-obvious behavior:
def _parse_boolean_expression(store: NodeStore, operator: str, operand_ids: list[NodeId]) -> BooleanSearch | None:
    operands = [expr for op_id in operand_ids if (expr := _parse_single_component(store, op_id))]
    return BooleanSearch(operator, operands) if operands else None
```

## DO NOT assemble non-plaintext by string concatenation (e.g., URL parameters)

Do not assemble URLs with plain string concat, e.g. `"&".join([f"{k}={v}" for k, v in params.items()])`. Use proper libraries:

**Wrong (various languages):**
```python
# Python
url = f"https://api.example.com/search?q={query}&limit={limit}"  # BAD: no escaping
html = f"<div title='{title}'>{content}</div>"  # BAD: manual string concat
html = f'<p class="{html.escape(css_class)}">'  # STILL BAD: manual string concat
sql = f"SELECT * FROM users WHERE name = '{username}'"  # BAD: SQL injection
```

```javascript
// JavaScript
const url = `https://api.example.com/search?q=${query}&limit=${limit}`;  // BAD
const html = `<div title="${title}">${content}</div>`;  // BAD
const sql = `SELECT * FROM users WHERE id = ${userId}`;  // BAD
```

```bash
# Bash
URL="https://api.example.com/search?q=$QUERY"  # BAD
SQL="SELECT * FROM users WHERE name = '$NAME'"  # BAD
```

**Right:**
```python
# URLs: Use requests (preferred) or urllib
response = requests.get("https://api.example.com/search", params={"q": query, "limit": limit})

# HTML: Use template engines or proper HTML builders
from jinja2 import Template
template = Template("<div title='{{ title }}'>{{ content }}</div>")
html = template.render(title=title, content=content)

# SQL: Use parameterized queries
cursor.execute("SELECT * FROM users WHERE name = %s", [username])

# JSON: Use json module
data = json.dumps({"name": name, "value": value})
```

This applies to *ANY* structured format. If it has special characters or escaping rules, use a library.

## CLI and Shell Tools

Examples of tools you can use without asking: `rg`, `jq`, `tree`, `ag`. Feel free to use any standard development tools.

## Avoid One-off Variables

Don't create variables used only once:
```python
# Wrong:
data = [update.dict() for update in updates]
await self._post_webhook({"type": "update", "data": data})

# Right:
await self._post_webhook({
    "type": "update",
    "data": [update.dict() for update in updates]
})
```

## Self-describing Variable Names

Include units/formats in names:
```python
# Wrong:
timeout: int
devices: list[str]

# Right:
timeout_secs: int
device_macs: list[str]

# Better (type encodes unit):
timeout: datetime.timedelta
```

# Python

## Code Style Philosophy
**Optimize for brevity and minimal cognitive load.** Fewer lines, fewer characters, less to hold in working memory.

## Formatting
1. Check for `.pre-commit-config.yaml` - use whatever formatter is configured there
2. If no pre-commit, use `black`
3. Remove unused imports before finishing

## Core Rules
- Imports at top (except for import loops)
- Use `pathlib` not `os.path`
- NEVER use `getattr`/`setattr` unless absolutely necessary

## Use Modern Python
```python
# Type hints - ALWAYS use new syntax
str | None                  # NOT Optional[str]
list[int]                   # NOT List[int]

# Features to use aggressively
f"{var=}"                   # Shows var='value'
text.removeprefix("pre_")   # NOT text[4:]
dict1 | dict2              # Merge dicts
if (n := len(items)) > 10:  # Walrus operator
match status:               # Pattern matching
    case "ok": return True
    case _: raise ValueError(f"Unknown {status=}")

# Use enums for fixed string sets
from enum import Enum
class Operator(Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"

# Wrong - stringly typed:
operator: str  # "AND", "OR", "NOT"

# Right - use enum:
operator: Operator
```


## Self-referencing Types

Use `typing.Self` or `from __future__ import annotations`:
```python
class X:
    def foo(self) -> Self:  # NOT -> "X"
        return self
```

## Walrus Operator

Use `:=` to combine assignment and test:
```python
# Wrong:
missing = configured - available_interfaces
if missing:
    logger.warning(f"Interfaces not found: {missing}")

# Also wrong:
expr = _parse_single_component(store, op_id)
if expr:
    operands.append(expr)

# Right:
if missing := configured - available_interfaces:
    logger.warning(f"Interfaces not found: {missing}")

if expr := _parse_single_component(store, op_id):
    operands.append(expr)
```

## Code Patterns

### NEVER use `hasattr` / `getattr` / `setattr`

**ABSOLUTELY FORBIDDEN when you control the code:**
```python
# WRONG - I HATE THIS:
if hasattr(piece, 'get_display_name'):
    return f"Temperature {piece.get_display_name()}"
return f"Temperature {piece.hardware_id}"
```

**Right:**
```python
return f"Temperature {piece.get_display_name()}"  # You KNOW it exists
```

## HTML Templating

As soon as you start doing nontrivial html operations/concatting, switch from manual html stitching to `jinja2` or other templating engine that contextually makes sense.

BAD: already **WAY TOO COMPLEX** for manual html stitching - **AND** prone to escaping issues:

```python
menu_html = '<nav class="menu">\n'
for page_id, page_title in menu_items:
    url = "/" if page_id == "index" else f"/{page_id}"
    active_class = ' class="active"' if page_id == active_page else ""
    menu_html += f'    <a href="{url}"{active_class}>{page_title}</a>\n'
menu_html += '</nav>\n'
html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>{content}</body>
</html>"""
```

This should have switched to `jinja2` about 10 minutes ago already.

## Logging

Inside exception handlers, logger methods automatically include exception info:

**Wrong:**
```python
try:
    risky_operation()
except ValueError as e:
    logger.error(f"Operation failed: {e}")  # BAD: duplicates exception info
```

**Right:**
```python
try:
    risky_operation()
except ValueError:
    logger.error("Operation failed")  # Good: exception details auto-included
```

## Testing

Test files should be located in the same directory as the module they're testing, with the name pattern `test_*.py`.

When writing unit tests, make them be pytest tests, **NOT** executable files with `__main__` section.

### PyHamcrest

Use `pyhamcrest` when testing sensor collections or complex matching scenarios. For example:

```python
# Instead of multiple `.next()` and assert calls:
assert_that(sensors, has_items(
    has_properties(unique_id="battery_level", state=50.0, icon="mdi:battery-50"),
    has_properties(unique_id="battery_state", state="discharging", icon="mdi:battery-minus"),
    has_properties(unique_id="battery_power", state=-10.0, unit_of_measurement="W", device_class=DeviceClass.POWER),
    has_properties(unique_id="battery_time_to_empty", state=3600, unit_of_measurement="s", device_class=DeviceClass.DURATION),
    has_properties(unique_id="battery_time_to_full", state=7200, unit_of_measurement="s", device_class=DeviceClass.DURATION),
))
```

This approach provides more readable and concise assertions, making it easier to verify complex object collections.

When looking for whether a sequence contains *one* element which meets some properties, use `has_item`.

DO NOT do:

```python
xs = [x for x in capture_updates if x.unique_id == "bluetooth_enabled"]
assert any(x.state == True and x.icon == "mdi:bluetooth" for x in xs)
```

ALSO DO NOT DO:

```python
from hamcrest import assert_that, has_items, has_properties
assert_that(
    capture_updates,
    has_items(
        has_properties(
            unique_id="bluetooth_enabled",
            state=True,
            icon="mdi:bluetooth"
        )
    )
)
```

Instead, DO do this:

```python
from hamcrest import assert_that, has_item, has_properties
assert_that(
    capture_updates,
    has_item(
        has_properties(
            unique_id="bluetooth_enabled",
            state=True,
            icon="mdi:bluetooth"
        )
    )
)
```

### When to use PyHamcrest vs standard assertions

Use standard Python assertions for basic checks that don't benefit from Hamcrest's matchers:

```python
# Use standard assertions when Hamcrest doesn't add value:
assert value == 200
assert user.name == "John"
assert foo is True
assert not bar
assert len(items) > 0
```

Use `pyhamcrest` when it makes the assertion more clear, expressive, or when you're doing complex checks:

```python
# Use Hamcrest for these cases:
# String content checking
assert_that(text, contains_string("success"))

# Dictionary content validation
assert_that(data, has_entries(status="ok", count=greater_than(0)))

# Multiple conditions
assert_that(
    response.text,
    all_of(
        contains_string("success"),
        contains_string("data")
    )
)
```

Access properties directly when using Hamcrest instead of using `has_property` when it doesn't add value:

WRONG - unnecessarily verbose:

```python
assert_that(user, has_property("name", contains_string("John")))
```

RIGHT - clearer and more direct:

```python
assert_that(user.name, contains_string("John"))
```

The rule of thumb is: if you're just doing a single test on an object and it's a basic equality/truthiness check, use standard assertions. Use Hamcrest when you need its matchers to simplify complex assertions.

If you notice you'd like to test your changes (which is of course highly encouraged), rather than writing one-off
blobs of throwaway Python, feel free to suggest creating a new actual test file.

## Handling Unhandled Cases

**ALWAYS handle the else case in switches/type checks. Crash on unexpected inputs.**

Actively check that the program stays within understood guardrails. As soon as something unexpected happens → CRASH.

```python
match msg:
    case SystemMessage(): return {"role": "system", "content": msg.content}
    case UserMessage(): return {"role": "user", "content": msg.content}
    case AssistantMessage(): return {"role": "assistant", "content": msg.content}
    case _: raise TypeError(f"Unexpected message type: {type(msg)}")
```

**Sometimes let natural exceptions serve as crashes:**
```python
# If this should NEVER fail (you control all callers):
operator_map = {AND_OPERATOR_ID: "AND", OR_OPERATOR_ID: "OR", NOT_OPERATOR_ID: "NOT"}
return _parse_boolean_expression(store, operator_map[operator_id], node.children[1:])
# KeyError here means a programming error - let it crash

# But if it's user input or external data, be explicit:
if operator_id not in operator_map:
    raise ValueError(f"Invalid operator: {operator_id}")
```

## Sentinel Objects

Using `None` as a default is fine when it means "nothing special" or "use default behavior":
```python
def format_data(data: str, formatter: Formatter | None = None):
    if formatter is None:
        return data  # No formatting, just return as-is
    return formatter.format(data)
```

Use sentinel objects when there's a semantic difference between passing `None` and not passing anything:

```python
# Example: JSON API where {"key": null} differs from {} (no key)
_UNSET = object()  # Sentinel value

def update_json_api(endpoint: str, key: str, value: Any = _UNSET):
    payload = {}
    if value is not _UNSET:
        # This handles both None and actual values
        payload[key] = value  # {"key": null} if value is None
    # If value is _UNSET, key is omitted entirely: {}
    return requests.post(endpoint, json=payload)
```

# Re-exporting Modules

Do not create new `__init__.py` files that re-export things from sibling/child modules, i.e. `__all__ == ["ThingFromSubmoduleA", "ThingFromSubmoduleB", ...]`

If you find yourself in a codebase that already has a well-established file like that, it's OK to continue using and adding to it.

But DO NOT create such a file yourself without my explicit permission.

# Final Rule

**When in doubt, CRASH.** Better to fail loudly than silently corrupt state.
