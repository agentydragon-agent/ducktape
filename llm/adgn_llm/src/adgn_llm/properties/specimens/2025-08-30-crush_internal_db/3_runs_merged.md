Runs: 1 = parallel_all, 2 = parallel_run2, 3 = parallel_run3

# internal/cmd/root.go

# internal/config/config.go
* [3] No unnecessary line breaks: Two consecutive blank lines in a struct block reduce readability. Lines 166167. Allow at most one blank line to separate logical sections.

* [3] No one-off variables or trivial passthrough wrappers: Singleuse variables immediately forwarded to the next call. Lines 8385. Example: client and path created only to be passed once into loadProvidersOnce(...). Inline without loss of clarity.

# internal/fsext/fileutil.go
* [1] No unnecessary nesting (combine trivial guards): Lines 9196: if d.IsDir() { if walker.ShouldSkip(path) { return filepath.SkipDir } return nil }. Flatten by checking combined guard first (d.IsDir() && walker.ShouldSkip(path)).

# internal/lsp/watcher/watcher.go
* [1 3] No oneoff variables or trivial passthrough wrappers: Temporary variables created only to immediately return or branch without adding meaning; inline the expression. Lines: 570577, 599603, 621623, 626631, 656658, 663665, 671673, 726729 (run 1); 621622, 626627, 656657, 663664, 671672, 726728 (run 3).
* [1] No unnecessary nesting (combine trivial guards): Nested cfg/LSP/name/WatchMode checks can be combined (ok && nonempty). Lines 6871. Nested cfg/LSP/name/RecursiveMaxWatchedDirs checks can be combined (> 0). Lines 7679.
