Runs: 1 = parallel_all, 2 = parallel_run2, 3 = parallel_run3

# internal/config/config.go
* [3] No unnecessary line breaks:
  Two consecutive blank lines in a struct block reduce readability.
  Lines 166–167. Allow at most one blank line to separate logical sections.


# internal/lsp/watcher/watcher.go
* [1] No one‑off variables or trivial pass‑through wrappers: Temporary variables created only to immediately return or branch without adding meaning; inline the expression. Lines: 570–577, 599–603, 621–623, 626–631, 656–658, 663–665, 671–673, 726–729.
* [1] No unnecessary nesting (combine trivial guards): Nested cfg/LSP/name/WatchMode checks can be combined (ok && non‑empty). Lines 68–71. Nested cfg/LSP/name/RecursiveMaxWatchedDirs checks can be combined (> 0). Lines 76–79.
