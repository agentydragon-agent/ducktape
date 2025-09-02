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
