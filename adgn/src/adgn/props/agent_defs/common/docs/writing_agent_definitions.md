# Agent Definition Authoring Guide

Agent definitions are self-contained packages:
- **AGENT.md** — System prompt
- **init** — Bootstrap script (must be executable, exit non-zero on failure)
- **bin/** — CLI tools (optional)
- **docs/** — Reference docs (optional)

Packed into tar archives and unpacked at `/workspace/` when run.

## Required Files

### `AGENT.md`
- Describe role and task clearly
- Specify input sources and output methods
- Reference docs: "See `docs/postgres_access.md`"
- Don't duplicate what init prints

### `init`
**Must be executable** (`chmod 0o755`). Runs before first sampling turn.

```python
#!/usr/bin/env python3
import sys
from sqlalchemy import text
from adgn.props.db import get_session

# Verify RLS context (CRITICAL)
with get_session() as session:
    agent_run_id = session.execute(text("SELECT current_agent_run_id()")).scalar()
    if not agent_run_id:
        print("ERROR: current_agent_run_id() is NULL", file=sys.stderr)
        sys.exit(1)
```

**Exit non-zero if:** RLS context is NULL, paths don't exist, DB fails.

## Output Size Limit

Init output must stay under `adgn.mcp.exec.models.MAX_BYTES_CAP`. If exceeded, agent run fails.

**To stay under:** Don't print large files directly — put them in `/workspace/docs/` for on-demand reading.

## Optional Files

### `bin/` — CLI Tools
Custom tools for structured output, database operations, validation.

### `docs/` — Reference Documentation

Supports executable lines with `!` prefix. When `print_docs()` processes a doc, lines starting with `!` are executed as shell commands and their output replaces the line.

Example in a doc file:

    ```markdown
    ## reported_issues table

    !psql -c "\d+ reported_issues"
    ```

When init runs, this becomes the live table description from the database.

Use cases: live schema docs (`!psql -c "\d+ tablename"`), tool versions (`!ruff --version`), env info (`!echo $PGDATABASE`).

## Security: No External Symlinks

Agent-created definitions cannot symlink outside the definition directory.

To reuse files from base definitions:
1. Fetch archive from database
2. Unpack to temp directory
3. Copy needed files into your definition
4. Pack your definition

## Container Environment

```
/workspace/                    # Your definition (read-write)
├── AGENT.md, init, bin/, docs/

/snapshots/{slug}/             # Source code (read-only)
```

## Definition Helpers

```python
from adgn.props.definition_utils import pack_definition, unpack_definition, validate_definition

errors = validate_definition(my_dir)
archive = pack_definition(my_dir, resolve_symlinks=False)
unpack_definition(archive, target_dir)
```

## Best Practices

1. Init fails fast — exit non-zero on any precondition failure
2. Print context in init — what agent needs goes into transcript
3. Custom tools for structured work — don't parse raw output
4. Don't duplicate docs — init prints it, AGENT.md doesn't repeat it
5. Verify before submit — tools can validate work
