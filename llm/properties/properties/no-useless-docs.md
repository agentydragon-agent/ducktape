---
title: No useless documentation or comments
kind: outcome
---

There are no comments/docstrings that merely restate what is obvious from the immediate context (nearby lines, function signature, class/module names).

## Scope
Applies only to code/docstrings/comments in agent‑added or agent‑edited hunks. Pre‑existing content outside those edits does not count toward violations. Excludes higher‑level documents (e.g., project READMEs) unless explicitly in scope.

## Acceptance criteria (checklist)
- No docstrings/comments that merely restate what is obvious from the immediate context (± a few lines, function signature, class/module names)
- Argument/return sections appear only when semantics/constraints are non‑obvious
- Evaluation scope: Only agent‑added or agent‑edited hunks are considered; redundant comments elsewhere in the file do not violate this property
- Keep module/class/function docs that capture contracts, invariants, side‑effects, or non‑obvious decisions
- Remove template boilerplate and generated stubs that provide no additional signal

## Positive examples (no boilerplate; not restating immediate context)
```python
from fastmcp import FastMCP
from typing import Any

def create_mcp_server(debug_mcp: bool = False) -> FastMCP[Any]:
    mcp: FastMCP[Any] = FastMCP("MCP Starter Template")

    @mcp.tool
    def greet(name: str) -> str:
        return f"hello, {name}"

    return mcp
```

## Negative examples (boilerplate restating immediate context)
```python
from fastmcp import FastMCP
from typing import Any

def create_mcp_server(debug_mcp: bool = False) -> FastMCP[Any]:
    """Create the MCP server with greeting functionality."""
    mcp: FastMCP[Any] = FastMCP("MCP Starter Template")

    @mcp.tool
    def greet(name: str) -> str:
        """Greet someone by name.

        Args:
            name: The name of the person to greet

        Returns:
            A greeting message
        """
        return f"hello, {name}"

    return mcp
```
