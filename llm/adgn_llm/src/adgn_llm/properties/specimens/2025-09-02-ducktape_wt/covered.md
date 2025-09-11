## [No dead code](../../props/no-dead-code.md)

- **wt/wt/server/gitstatusd_client.py**:
  - dead code: `branch_status`; remove.
    GAP: Presentation/view concerns (branch display state) should not live in the core client.
- **wt/wt/server/wt_server.py**:
  - 1425–1430 — Redundant conditional block duplicated (same membership check twice); remove the duplicate branch.
    GAP: Choose a consistent layer for conversion (e.g., relative→absolute) and apply it symmetrically across inputs; avoid split responsibility. This is like the finidng  on MIN_GIT_REPO_FIELDS repeated checking.

## [Use pathlib for path manipulation](../../props/python/pathlib.md)
- **wt/wt/server/wt_server.py**:
  - 2501–2502 —
    prefer one-liner Path I/O form: `self.pid_file.write_text(str(os.getpid()))`.
    (Applies to any simple two-line "with open(..., 'w') as f; f.write(...)" pattern where `Path.write_text(...)` suffices, no big perf concerns etc.)

    This is async context writing as a synchronous write. Some linters would complain here.
    GAP: Provide guidance for blocking I/O in async contexts (when allowed, preferred non-blocking patterns) and document exceptions.
