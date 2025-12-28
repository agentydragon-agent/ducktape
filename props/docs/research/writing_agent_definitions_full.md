# Agent Definition Authoring Guide

This guide is for agents that **dynamically create** agent definitions (e.g., prompt optimizer creating custom critics). It covers the required structure, security constraints, and patterns for building effective definitions.

## Overview

Agent definitions are stored as **tarballs (Docker build contexts)** in the database. Each tarball contains:

- **Dockerfile** — Build recipe (required)
- **AGENT.md** — System prompt (typically COPY'd to /AGENT.md)
- **init** — Bootstrap script (typically COPY'd to /init, must be executable)
- **Python packages** — Bundled dependencies with their docs

**Image contract:** Built Docker image must have `/init` (executable) and `/AGENT.md`.

## Common Workflow

```bash
# Fetch base definition (unpacks full tarball including Dockerfile)
props agent-definition fetch <id> /workspace/my_critic/

# Modify AGENT.md (and optionally Dockerfile, init, packages)
# You have full control — can modify anything

# Pack and insert new definition
props agent-definition create /workspace/my_critic/
```

## Required Files

### `AGENT.md` — System Prompt

Your system prompt is injected as the first message in the agent's conversation.

**Content guidelines:**
- Describe the agent's role and task clearly
- Specify input sources (MCP resources, database tables, mounted paths)
- Specify output methods (CLI tools, MCP tools, database writes)
- Include workflow steps and concrete examples
- Reference documentation files: "See `docs/postgres_access.md`"

**What NOT to include:**
- Content already printed by the init script
- Generic instructions that apply to all agents
- Tool schemas (auto-generated from MCP)

### `init` — Bootstrap Script

**MUST be executable** (`chmod 0o755`).

Runs BEFORE the agent's first sampling turn. Timeout: 15 seconds.

**Purpose:**
1. Verify environment and preconditions
2. Print context into the agent's transcript
3. Fail fast if something is wrong

**Critical: Exit non-zero on failures:**

```python
#!/usr/bin/env python3
import sys
from pathlib import Path
from sqlalchemy import text
from props_core.db import get_session

# 1. Verify RLS context (CRITICAL)
with get_session() as session:
    agent_run_id = session.execute(text("SELECT current_agent_run_id()")).scalar()
    if not agent_run_id:
        print("ERROR: current_agent_run_id() is NULL - RLS will block writes", file=sys.stderr)
        sys.exit(1)
    print(f"Agent run ID: {agent_run_id}")

# 2. Verify expected paths exist
snapshot_path = Path("/snapshots/my-snapshot")
if not snapshot_path.is_dir():
    print(f"ERROR: Snapshot not found: {snapshot_path}", file=sys.stderr)
    sys.exit(1)

# 3. Print context for the agent
print("=== Review Context ===")
print(f"Source code: {snapshot_path}")
print("Ready to begin.")
```

**Must exit non-zero if:**
- `current_agent_run_id()` returns NULL (RLS will silently block all writes)
- Required directories don't exist
- Database connection fails
- MCP resources are unreadable
- Any other precondition fails

## Output Size Limit

Your init script output must stay under the limit defined by `mcp_infra.exec.models.MAX_BYTES_CAP` (stdout + stderr combined). Check the current value:

```python
from mcp_infra.exec.models import MAX_BYTES_CAP
print(f"Limit: {MAX_BYTES_CAP} bytes ({MAX_BYTES_CAP // 1000}KB)")
```

**If exceeded:** The agent run fails immediately. You'll see an error like:
```
Init script failed: Init script output was truncated (stdout: 45000 bytes total).
```

**To stay under the limit:**
1. Don't print large files directly — docs are in Python packages for on-demand reading
2. Print summaries, not full content (e.g., file counts, not file contents)
3. Use `print_bootstrap()` which handles common context efficiently

## Optional Files

### `bin/` — CLI Tools

Custom tools the agent can invoke via shell. Useful for:
- Structured output (parse tool output into JSON)
- Multi-step operations (run analysis, filter, format)
- Database operations (wrap complex SQL)
- Validation (check work before submission)

**Example:**

```python
#!/usr/bin/env python3
# bin/analyze
"""Analyze code and output structured JSON."""
import subprocess
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/snapshots"

result = subprocess.run(
    ["ruff", "check", path, "--output-format", "json"],
    capture_output=True, text=True
)

findings = json.loads(result.stdout) if result.stdout else []
print(json.dumps(findings, indent=2))
```

The agent calls `bin/analyze /snapshots/foo/` instead of parsing raw output.

### Python Package Docs

Documentation lives in Python packages (e.g., `props_agent_util/docs/`). The `print_bootstrap()` function reads docs from package resources and prints them to the transcript.

Docs support executable lines with `!` prefix — lines starting with `!` are executed as shell commands and replaced with their output.

Example in a doc file:

    ```markdown
    ## reported_issues table

    !psql -c "\d+ reported_issues"
    ```

Use cases: live schema docs (`!psql -c "\d+ tablename"`), tool versions (`!ruff --version`).

## Security: No External Symlinks

**Agent-created definitions cannot use symlinks to files outside the definition directory.**

This prevents directory escape attacks (e.g., symlinking to `/etc/passwd`).

When you pack a definition with `pack_definition(path)`:
- External symlinks raise `ValueError`
- Internal symlinks (within the definition) are allowed
- Dockerfile must be present

## Reusing Files from Base Definitions

Use the CLI to fetch and modify base definitions:

```bash
# Fetch base definition (includes Dockerfile, init, AGENT.md, packages)
props agent-definition fetch <id> /workspace/my_critic/

# Modify what you need
# Edit AGENT.md, Dockerfile, init, etc.

# Pack and insert
props agent-definition create /workspace/my_critic/
```

For programmatic access, see the `props.definition_utils` module.

## Container Environment

At runtime, the built Docker image has:

```
/                              # Container root
├── init                       # Executable bootstrap script
├── AGENT.md                   # System prompt
└── ...                        # Installed Python packages

/snapshots/{slug}/             # Source code (fetched by init at runtime)
/workspace/                    # Working directory (empty at start)
```

For database access, MCP connection, and RLS scoping, see the docs in `props_agent_util`.

## Definition Helpers

Use the CLI (preferred):

```bash
props agent-definition fetch <id> /workspace/my_def/   # unpack base
props agent-definition create /workspace/my_def/       # pack and insert
```

Or Python API (see `props.definition_utils` for details):

```python
from props_core.definition_utils import pack_definition, unpack_definition

archive = pack_definition(my_dir)  # validates Dockerfile exists
unpack_definition(archive, target_dir)
```

## Best Practices

1. **Init fails fast** — Check every precondition. Exit non-zero immediately on failure.

2. **Print context in init** — Whatever the agent needs to know goes into the transcript.

3. **Custom tools for structured work** — Instead of parsing raw output, write tools that structure it.

4. **Don't duplicate docs** — If init prints something, don't repeat it in AGENT.md.

5. **Use the CLI pattern** — Typer-based CLIs in `bin/` give clear, documented commands.

6. **Verify before submit** — Tools can validate work. E.g., list reported issues before final submit.

7. **Design for your task** — There's no required I/O pattern. Use whatever fits.

## Common Patterns

### Minimal Custom Critic

```
my_critic/
├── Dockerfile        # Build recipe (COPY init, AGENT.md, install packages)
├── AGENT.md          # System prompt
├── init              # Verify snapshot, DB, print context
└── bin/
    └── check         # Custom analysis tool
```

### Full-Featured Agent

```
my_agent/
├── Dockerfile        # Build recipe
├── AGENT.md          # Complete task description
├── init              # Environment verification + context
├── bin/
│   ├── analyze       # Run analysis
│   ├── report        # Generate reports
│   └── submit        # Final submission
└── props_agent_util/ # Bundled package with docs
```

## Validation

The `pack_definition()` function validates that Dockerfile exists. The image build validates that `/init` and `/AGENT.md` are present in the final image.
