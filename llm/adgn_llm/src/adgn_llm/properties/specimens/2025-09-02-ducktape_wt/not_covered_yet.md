## Dirty-state copy is never triggered

- Client only sends `source_branch`, so the daemon passes `None`; as a result, a dirty-state copy never happens.

## RPC surface: worktree identity contract

- `source_worktree` on the RPC violates the implicit contract that worktrees are identified by WorktreeID (opaque), not by alternative identifiers.

## Teleport resolution on client instead of server

- Client performs teleport resolution client-side rather than via the server, counter to the architectural intent.

## other

worktree_utils: create_worktree if/else has duplicated code, should first branch to identify source branch, then in shared trunk call create RPC.

in worktree_utils:
```python
def get_current_worktree_info(config) -> tuple[Path | None, str | None]:
    """Get current worktree information."""
    cwd = Path.cwd()
```
the function does not describe what either parameter is and it's not clear from the code either.
should either be documented in docstring or changed to return a descriptive dataclass/struct.
there is a general heuristic kinda like "do not return tuples/lists/... unless it's very clear what each member means".
