## Dirty-state copy is never triggered

- Client only sends `source_branch`, so the daemon passes `None`; as a result, a dirty-state copy never happens.

## RPC surface: worktree identity contract

- `source_worktree` on the RPC violates the implicit contract that worktrees are identified by WorktreeID (opaque), not by alternative identifiers.

## Teleport resolution on client instead of server

- Client performs teleport resolution client-side rather than via the server, counter to the architectural intent.

## other

- wt/wt/server/git_manager.py: `log_format` ignores its `format_str` parameter and the only caller (`wt/wt/server/worktree_service.py`:62) immediately parses the string back. Replace with a structured return (no format+parse roundtrip).
- wt/wt/server/wt_server.py (_run_post_creation_script_streaming):
  - Return shape includes `ran` (always True) and `error` (always None) — remove redundant fields and signal errors via exceptions; return a structured result object.
  - Output forwarding collects stdout/stderr as lines with repeated `.decode(errors="replace")` and rejoins. Prefer reading raw bytes and either returning byte buffers or decoding once at the boundary; avoid lossy line-based decoding unless the consumer requires line semantics.
- wt/wt/shared/protocol.py:29–31 — Prefer `str.removeprefix("wtid:")` over slicing (`wtid[5:]`) for fixed-prefix removal (mirrors our Python convention).
- wt/tests/integration/test_shell_integration.py: prefer simple assertions over `pytest.fail(...)`; use `assert len(parts) == 5, f"Bad output: {s}"` at 229; assert non-empty `output_lines` at 156–157; apply the same assert style at ~163–164.

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
