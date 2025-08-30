Runs: 1 = parallel_all, 2 = parallel_run2, 3 = parallel_run3

internal/app/app.go
* [1] Early bailout: loop guard should use continue (cleanup funcs)
* [1] No unnecessary nesting: flatten trivial guards in MCP topic derivation
* [1 3] No trivial pass-through wrappers: UpdateAgentModel forwards without value
* [1 2] Self‑describing names: readBts → readBytes (bytes)
* [1 2] Self‑describing names: maxSize → maxSizeMB; maxAge → maxAgeDays

internal/app/lsp_events.go
* [1] Early bailout: use early return instead of wrapping entire body

internal/cmd/root.go
* [1] No one-off variables: single-use yolo forwarded into cfg
* [1 3] Self‑describing names: boolean flag/name yolo unclear; use descriptive predicate

internal/config/config.go
* [3] No unnecessary line breaks: two consecutive blank lines in struct

internal/config/provider.go
* [3] No one‑off variables: single‑use temps forwarded to next call

internal/csync/maps.go
* [1 2 3] No one-off variables: JSONSchemaAlias returns throwaway temp; inline literal

internal/diff/word_inline.go
* [2] Use filepath.Join instead of string concatenation for paths

internal/format/spinner.go
* [2] No one-off variables: inline single-use local model
* [2] No one-off variables: inline single-use local prog into struct

internal/fsext/fileutil.go
* [1] No unnecessary nesting: combine trivial guards (dir + skip)
* [1] Self‑describing names: DirTrim params (pwd, lim) should encode meaning/units

internal/fsext/ignore_test.go
* [1] Self‑describing names: oldWd → clearer prev dir name

internal/fsext/ls.go
* [1] No unnecessary nesting: combine ignore && isDir guard

internal/history/file.go
* [1] No unnecessary nesting: flatten nested UNIQUE constraint retry guard
* [1 2 3] Self‑describing timestamps: CreatedAt/UpdatedAt int64 → time.Time or unit‑suffixed

internal/logging/recover.go
* [1 2] Early bailout: prefer early return over wrapping whole body after recover

internal/llm/prompt/anthropic.md
* [1 3] Markdown: use inline code for file names, commands, and paths (e.g., `CRUSH.md`, `package.json`, `npm run lint`)

internal/llm/prompt/gemini.md
* [1 3] Markdown: use code spans for files/commands instead of quotes; format `CRUSH.md`

internal/llm/prompt/init.md
* [1 3] Markdown: use fenced code blocks for multi‑line; `CRUSH.md` as inline code

internal/llm/prompt/openai.md
* [1 3] Markdown: inline code for file names, identifiers, and paths; format `CRUSH.md`

internal/llm/prompt/v2.md
* [1 3] Markdown: inline code for file names, commands, and paths; format `CRUSH.md`

internal/llm/tools/download.go
* [3] Self‑describing names: maxSize → maxSizeBytes; maxTimeout → maxTimeoutSecs; Timeout int → TimeoutSecs or time.Duration

internal/llm/tools/tools.go
* [3] Self‑describing names: StartedAt/UpdatedAt int64 are ms epoch; suffix units or use time types

internal/lsp/client.go
* [1] Early bailout: loop guard should use continue (file existence)
* [3] Early bailout: unnecessary else after early return

internal/lsp/watcher/watcher.go
* [1 3] No one‑off variables: inline single‑use temporaries
* [1 3] Self‑describing names: maxFileSize → maxFileSizeBytes
* [1] No unnecessary nesting: combine trivial cfg/name guards
* [3] No unnecessary nesting: redundant duplicate basePath == "" guard

internal/message/content.go
* [1 2] No unnecessary nesting: flatten nested type/id/finished guards across helpers
* [1 2] Self‑describing timestamps: StartedAt/FinishedAt/CreatedAt/UpdatedAt int64 → time types or unit‑suffixed
* [1 2] Self‑describing names: Finish.Time int64 lacks unit → time.Time or unit‑suffixed

internal/message/message.go
* [1 2 3] Early bailout: use continue instead of wrapping loop body (DeleteSessionMessages)
* [1 2 3] Self‑describing timestamps: Watermarks.*TS and Message timestamps → time types or unit‑suffixed
* [1] Inconsistent units: UpdatedAt set in microseconds without unit suffix
* [3] Self‑describing names: ambiguous id params (interface Delete, Delete(ctx, id string)) → messageID

internal/message/middleware/debounce.go
* [3] Self‑describing names: id params represent message IDs → messageID

internal/message/middleware/serialized.go
* [3] Self‑describing names: sessionWorker.id/newSessionWorker(id)/Delete(ctx, id)/op.createSess/op.deleteID → sessionID/messageID

internal/profile/profile.go
* [1] Self‑describing names: s/v too terse; use address/storedAddr, etc.

internal/profile/server.go
* [1] Self‑describing names: v for CRUSH_PROFILE; pstr for pprof port → clearer names

internal/pubsub/broker.go
* [1 3] Self‑describing timestamps: now := time.Now().UnixMilli() → time type or nowUnixMs
* [2 3] No unnecessary nesting/one‑off vars: use short if with s := f.String(); s != "" { ... }

internal/session/session.go
* [1 2 3] Self‑describing timestamps: CreatedAt/UpdatedAt int64 → time types or unit‑suffixed
* [1] Self‑describing names and types: Cost float64 ambiguous; encode currency/scale and prefer fixed‑point
* [2 3] No one‑off variables: inline single‑use broker into struct literal

internal/shell/shell.go
* [1 2 3] Early bailout: loop guard should use continue; avoid wrapping body
* [3] Early bailout: use labeled continue instead of sentinel flag in inner loop

internal/tui/components/chat/chat.go
* [3] No unnecessary nesting: flatten nested ifs on type assertions and ID equality
* [3] Self‑describing timestamps: lastUserMessageTime int64 epoch seconds → time.Time or unit‑suffixed

internal/tui/components/chat/messages/renderer.go
* [3] Self‑describing durations: timeout int seconds → timeoutSeconds or time.Duration

internal/transform/transform.go
* [1 2 3] Self‑describing timestamps: CreatedAt int64 → time.Time or explicit unit suffix
