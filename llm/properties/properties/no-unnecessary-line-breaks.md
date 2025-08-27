---
title: No unnecessary line breaks
kind: outcome
---

The parse tree is laid out in the minimum number of lines allowed by the configured linter, except where newlines are deliberately added to improve readability.
If code can fit on one line without harming readability and the linter would preserve it, it does.

## Scope
Applies only to agent‑added or agent‑edited hunks. Pre‑existing formatting outside those edits does not count toward violations.

## Acceptance criteria (checklist)
- Calls/constructors with short argument lists are on one line when the linter would not split them
- Expressions that can be a single line without reducing readability are written on one line
- It is acceptable to add at most one blank line to separate logical sections (e.g., Arrange/Act/Assert in tests)
- It is acceptable to break lines deliberately for readability (e.g., multi‑line string assembly), even if a single line would be valid
- Do not introduce two or more consecutive blank lines for spacing

## Positive examples
```python
# One-line constructor call (readable; linter keeps it on one line)
img = ImageContent(type="image", data=red_pixel_png, mimeType="image/png")

# Intentional section spacing (at most one blank line)
# Arrange
foo = make_foo()
foo.prepare()

# Act
foo.activate()

# Multi-line string assembly for readability
headers = (
    "Content-Type: text/plain; charset=utf-8\n"
    "X-Env: prod\n"
    "X-Request-Id: 123\n"
)
```

## Negative examples
```python
# Unnecessarily split call with identical parse tree; should be single line
img = ImageContent(
    type="image",
    data=red_pixel_png,
    mimeType="image/png",
)

# Excessive blank spacing (more than one empty line between sections)
# Arrange
foo = make_foo()


# Act
foo.activate()

# Gratuitous line breaks that neither improve readability nor are required by the linter
value = (
    compute_value()
)
```

### SonicBrowser configuration examples

#### Negative examples (identical parse tree, unnecessary breaks)
```python
def create_sonic_browser_config() -> ToolConfig:
    """Create configuration for SonicBrowserTool."""
    return ToolConfig(
        name="sonic_browser",
        tool_class=SonicBrowserDelegatingTool,
        constructor_params={
            "caller": "adgn_sonic_lean_mcp",
            # Additional SonicBrowser configuration can be added here
        },
        methods={
            "search": MethodConfig(
                mcp_name="search_web",
                description=_prompt_latest(),
                parameters={
                    "query": str,
                    "session_id": str,
                },
                session_handling=SessionHandling.CREATE_IF_MISSING,
                record_navigation=True,
            ),
        },
    )
```

#### Positive examples (same parse tree, compact layout)
```python
# Additional SonicBrowser configuration can be added here
constructor_params={"caller": "adgn_sonic_lean_mcp"}
parameters={"query": str, "session_id": str}
```
