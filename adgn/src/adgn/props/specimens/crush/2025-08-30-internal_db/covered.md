## [Self-describing names](../../props/self-describing-names.md)

* `internal/fsext/fileutil.go`: DirTrim params (pwd, lim) should encode meaning/units
* `internal/fsext/ignore_test.go`: oldWd → clearer prev dir name
* `internal/session/session.go`: Cost float64 ambiguous; encode currency/scale and prefer fixed‑point

### File sizes

* `internal/lsp/watcher/watcher.go`: maxFileSize → maxFileSizeBytes
* `internal/app/app.go`: readBts → readBytes (bytes); maxSize → maxSizeMB; maxAge → maxAgeDays
* `internal/llm/tools/download.go`: maxSize → maxSizeBytes
