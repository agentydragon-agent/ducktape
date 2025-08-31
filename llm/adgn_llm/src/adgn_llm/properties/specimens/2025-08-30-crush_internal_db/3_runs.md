Runs: 1 = parallel_all, 2 = parallel_run2, 3 = parallel_run3

# internal/cmd/root.go
* [1] No one-off variables or trivial pass-through wrappers:
  yolo is a single‑use variable that immediately forwards into cfg.Permissions.SkipRequests without adding clarity. Lines 133, 168. Rationale: Single‑use forwarding variables should be inlined unless they add non‑obvious value.
* [1 3] Self‑describing names for primitives (units and meaning):
  The boolean flag and variable name yolo are not self‑descriptive. Lines 30 (CLI flag), 133, 168. Prefer names like --auto-accept / autoAccept or --skip-permission-requests / skipPermissionRequests; booleans should be clear predicates like dangerous_mode, auto_accept_permissions, or skip_requests.

# internal/config/config.go
* [3] No unnecessary line breaks:
  Two consecutive blank lines in a struct block reduce readability.
  Lines 166–167. Allow at most one blank line to separate logical sections.

# internal/config/provider.go
* [3] No one-off variables or trivial pass‑through wrappers:
  Single‑use variables immediately forwarded to the next call.
  Lines 83–85.
  Example: client and path created only to be passed once into loadProvidersOnce(...). Inline without loss of clarity.

# internal/fsext/fileutil.go
* [1] No unnecessary nesting (combine trivial guards): Lines 91–96: if d.IsDir() { if walker.ShouldSkip(path) { return filepath.SkipDir } return nil }. Flatten by checking combined guard first (d.IsDir() && walker.ShouldSkip(path)).

# internal/lsp/watcher/watcher.go
* [1] No one‑off variables or trivial pass‑through wrappers: Temporary variables created only to immediately return or branch without adding meaning; inline the expression. Lines: 570–577, 599–603, 621–623, 626–631, 656–658, 663–665, 671–673, 726–729.
* [1] No unnecessary nesting (combine trivial guards): Nested cfg/LSP/name/WatchMode checks can be combined (ok && non‑empty). Lines 68–71. Nested cfg/LSP/name/RecursiveMaxWatchedDirs checks can be combined (> 0). Lines 76–79.
* [3] No unnecessary nesting (combine trivial guards): Redundant duplicate guard on basePath == "" in matchesPattern; the second check is unreachable and increases branching without benefit. Lines 699–705 and 707–709.
