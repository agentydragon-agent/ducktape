## Duplicate hydration/post-creation script invocation paths

- There are two implementations of the hydration + post-creation script invocation, one inside the worktree service and one outside; production path is separate and not invoked by tests.
- This creates parallel implementations (one effectively test-only), leading to drift and untested production behavior.

## Dirty-state copy is never triggered

- Client only sends source_branch, so the daemon passes None; as a result, a dirty-state copy never happens.

## RPC surface: worktree identity contract

- `source_worktree` on the RPC violates the implicit contract that worktrees are identified by WorktreeID (opaque), not by alternative identifiers.

## Teleport resolution on client instead of server

- Client performs teleport resolution client-side rather than via the server, counter to the architectural intent.

## Test fixture duplication: cwd manager

- Test suite contains a hand-rolled cwd manager fixture duplicating standard pytest monkeypatch capabilities; should consolidate on pytest facilities.

## other

`logging_config.py`: `OperationLogger` is dead code - it has no references anywhere. There are more issues inside it (e.g. should inline `extra_fields` in both `log_operation` and `log_error`), but it should just generally not exist. With that class deleted, `JSONFormatter` is also unused.

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
