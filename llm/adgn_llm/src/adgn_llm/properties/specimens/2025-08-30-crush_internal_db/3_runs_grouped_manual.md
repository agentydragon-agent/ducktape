### TBD

internal/cmd/root.go
* No one-off variables: single-use yolo forwarded into cfg
* Self‑describing names: boolean flag/name yolo unclear; use descriptive predicate

internal/config/config.go
* No unnecessary line breaks: two consecutive blank lines in struct

internal/config/provider.go
* No one‑off variables: single‑use temps forwarded to next call

internal/lsp/watcher/watcher.go
* No one‑off variables: inline single‑use temporaries
* No unnecessary nesting: combine trivial cfg/name guards
* No unnecessary nesting: redundant duplicate basePath == "" guard

internal/tui/components/chat/chat.go
* No unnecessary nesting: flatten nested ifs on type assertions and ID equality
