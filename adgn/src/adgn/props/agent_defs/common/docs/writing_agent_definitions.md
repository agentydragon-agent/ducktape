# Agent Definition Authoring Guide

This guide is for agents that **dynamically create** agent definitions (e.g., prompt optimizer creating custom critics). It covers the required structure, security constraints, and patterns for building effective definitions.

## Overview

Agent definitions are self-contained packages that define an agent's behavior:
- **AGENT.md** — System prompt (what the agent should do)
- **init** — Bootstrap script (verify environment, print context)
- **bin/** — CLI tools (optional, for structured operations)
- **docs/** — Reference documentation (optional)

Definitions are packed into tar archives, stored in the database, and unpacked into Docker containers at `/workspace/` when run.

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
from adgn.props.db import get_session

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

Your init script output must stay under the limit defined by `adgn.mcp.exec.models.MAX_BYTES_CAP` (stdout + stderr combined). Check the current value:

```python
from adgn.mcp.exec.models import MAX_BYTES_CAP
print(f"Limit: {MAX_BYTES_CAP} bytes ({MAX_BYTES_CAP // 1000}KB)")
```

**If exceeded:** The agent run fails immediately. You'll see an error like:
```
Init script failed: Init script output was truncated (stdout: 45000 bytes total).
```

**To stay under the limit:**
1. Don't print large files directly — put them in `/workspace/docs/` and read on demand
2. Print summaries, not full content (e.g., file counts, not file contents)
3. Use `print_bootstrap()` which handles common context efficiently
4. For reference material, create files the agent can `cat` when needed

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

The agent calls `/workspace/bin/analyze /snapshots/foo/` instead of parsing raw output.

### `docs/` — Reference Documentation

Put detailed docs here. The init script can print key docs, or the agent can read on demand.

#### Executable Lines in Documentation

Documentation files support executable lines with the `!` prefix. When `print_docs()` processes a doc file, lines starting with `!` are executed as shell commands and their output replaces the line.

**Example:**

    ```markdown
    ## reported_issues

    !psql -c "\d+ reported_issues"
    ```

When the init script runs, `!psql -c "\d+ reported_issues"` is replaced by the actual table description (columns, types, comments) from the database.

**Use cases:**
- Live schema documentation: `!psql -c "\d+ tablename"` shows current column types and constraints
- Environment info: `!echo $PGDATABASE` shows which database is connected
- Tool versions: `!ruff --version` shows installed linter version

**Guidelines:**
- Commands must succeed (`check=True`) — failed commands crash init
- Keep commands fast — they run on every init
- Use for dynamic content that can't be statically documented

## Reading Files from Python Packages

Init scripts can read files from installed Python packages using `importlib.resources`. This is useful for printing helper functions or shared code:

```python
from importlib import resources

# Print helper functions from the adgn package
helpers = resources.files("adgn.props.critic").joinpath("helpers.py")
print(helpers.read_text())
```

**When to use:**
- Printing helper modules that the agent should know about
- Showing shared utilities from the adgn package
- Displaying configuration files from packages

**When NOT to use:**
- For docs already in `/workspace/docs/` — just let `print_docs()` handle them
- For ORM models — use `!psql` commands in docs instead

## Security: No External Symlinks

**Agent-created definitions cannot use symlinks to files outside the definition directory.**

This prevents directory escape attacks (e.g., symlinking to `/etc/passwd`).

When you pack a definition with `pack_definition(path, resolve_symlinks=False)`:
- External symlinks raise `ValueError`
- Internal symlinks (within the definition) are allowed
- All files must be explicitly included

**If you need files from another definition**, you must:
1. Fetch the archive from the database
2. Unpack it to a temp directory
3. Copy the files you need into your definition
4. Pack your definition

## Reusing Files from Base Definitions

To inherit from an existing definition (e.g., base critic):

```python
from adgn.props.db import get_session
from adgn.props.db.models import AgentDefinition
from adgn.props.definition_utils import unpack_definition, pack_definition
from pathlib import Path
import tempfile
import shutil

def create_custom_definition(custom_agent_md: str) -> bytes:
    """Create a custom definition based on the critic."""

    # 1. Fetch base definition
    with get_session() as session:
        base_def = session.get(AgentDefinition, "critic")
        base_archive = base_def.archive

    with tempfile.TemporaryDirectory() as tmpdir:
        # 2. Unpack base
        base_dir = Path(tmpdir) / "base"
        unpack_definition(base_archive, base_dir)

        # 3. Create your definition
        my_dir = Path(tmpdir) / "my_definition"
        my_dir.mkdir()

        # 4. Copy files you need from base
        shutil.copy(base_dir / "init", my_dir / "init")
        shutil.copy(base_dir / "init_helpers.py", my_dir / "init_helpers.py")
        shutil.copytree(base_dir / "bin", my_dir / "bin")
        shutil.copytree(base_dir / "docs", my_dir / "docs")

        # 5. Write your custom AGENT.md
        (my_dir / "AGENT.md").write_text(custom_agent_md)

        # 6. Add custom tools (optional)
        my_tool = my_dir / "bin" / "my_tool"
        my_tool.write_text(MY_TOOL_SCRIPT)
        my_tool.chmod(0o755)

        # 7. Pack (resolve_symlinks=False for security)
        return pack_definition(my_dir, resolve_symlinks=False)
```

## Container Environment

When your definition runs:

```
/workspace/                    # Your unpacked definition (read-write)
├── AGENT.md
├── init
├── bin/
├── docs/
└── ...

/snapshots/{slug}/             # Source code (read-only, if mounted)
```

See `docs/postgres_access.md` for database env vars, `docs/mcp_http_connection.md` for MCP access, `docs/rls_mechanism.md` for RLS scoping.

## Definition Helpers

Use `adgn.props.definition_utils` to work with definitions:

```python
from adgn.props.definition_utils import pack_definition, unpack_definition, validate_definition

# Validate structure
errors = validate_definition(my_dir)

# Pack (resolve_symlinks=False for security)
archive = pack_definition(my_dir, resolve_symlinks=False)

# Unpack
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
├── AGENT.md          # "Review code for X. Use /workspace/bin/check..."
├── init              # Verify snapshot, DB, print context
└── bin/
    └── check         # Custom analysis tool
```

### Full-Featured Agent

```
my_agent/
├── AGENT.md          # Complete task description
├── init              # Environment verification + context
├── init_helpers.py   # Shared functions for init
├── bin/
│   ├── analyze       # Run analysis
│   ├── report        # Generate reports
│   └── submit        # Final submission
├── docs/
│   ├── workflow.md   # Detailed workflow
│   └── examples.md   # Example patterns
└── examples/
    └── sample.py     # Example script
```

## Validation

Before inserting a definition, validate it:

```python
from adgn.props.definition_utils import validate_definition

errors = validate_definition(my_dir)
if errors:
    print(f"Invalid: {errors}")
```

Checks:
- `AGENT.md` exists
- `init` exists and is executable
