## [Truthfulness](../../definitions/truthfulness.md)

- Misleading name/doc: `getFileExtension` returns synthesized file names (fake paths), not an extension; rename and update doc to reflect actual return value.
- Identifier typo: `isValidUt8` -> `isValidUTF8` in `fetch.go`/`view.go`.

### Path schema/docs inconsistent with behavior

- `internal/llm/tools/`: inconsistent - schema/docs and behavior should be aligned:
  - `ls.go`: ToolInfo.Required lists "path" as required, but Run allows empty path and defaults to workingDir (e.g., lines 119–123, 536–543). 
  - `edit.go`: Description (lines 48–104) says absolute path only, but Run joins relative paths with workingDir (lines 155–157).

Align docs/schema and code (either make code behave as docs/schema prescribe, or update docs/schema to match behavior).

## [Self-describing names](../../definitions/self-describing-names.md)

* `internal/profile/profile.go`: s/v too terse; use address/storedAddr, etc.
* `internal/profile/server.go`: v for CRUSH_PROFILE; pstr for pprof port → clearer names
* `internal/fsext/fileutil.go`: DirTrim params (pwd, lim) should encode meaning/units
* `internal/fsext/ignore_test.go`: oldWd → clearer prev dir name
* `e2e/setup_helpers.go`: `b` nondescriptive name, use e.g. "compressEnabled"
* `internal/session/session.go`: Cost float64 ambiguous; encode currency/scale and prefer fixed‑point

### Timestamps

Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int, suffix units in names).

* `internal/llm/tools/`:
  * `download.go`: `maxTimeout` and `Timeout` → `...Secs` or `time.Duration`
  * `fetch.go`: `Timeout int`
  * `tools.go`: `StartedAt`/`UpdatedAt int64` are ms epoch
* `internal/message/`:
  * `content.go`: `{Started,Finished,Created,Updated}At`, `Finish.Time` → time types or unit‑suffixed
  * `message.go`:
    * Watermarks.*TS and Message timestamps → time types or unit‑suffixed
    * Inconsistent units: UpdatedAt set in microseconds without unit suffix
* `internal/history/file.go`: CreatedAt/UpdatedAt int64 → time.Time or unit‑suffixed
* `internal/tui/components/chat/`:
  * `chat.go`: lastUserMessageTime int64 epoch seconds → time.Time or unit‑suffixed
  * `messages/renderer.go`: timeout int seconds → timeoutSeconds or time.Duration
* `internal/pubsub/broker.go`: now := time.Now().UnixMilli() → time type or nowUnixMs
* `internal/session/session.go`: CreatedAt/UpdatedAt int64 → time types or unit‑suffixed
* `internal/transform/transform.go`: CreatedAt int64 → time.Time or explicit unit suffix

### IDs

* `internal/message/middleware`:
  * `debounce.go`: id params represent message IDs → messageID
  * `serialized.go`: sessionWorker.id/newSessionWorker(id)/Delete(ctx, id)/op.createSess/op.deleteID → sessionID/messageID
* `internal/message/message.go`: ambiguous id params (interface Delete, Delete(ctx, id string)) → messageID

### File sizes

* `internal/lsp/watcher/watcher.go`: maxFileSize → maxFileSizeBytes
* `internal/app/app.go`: readBts → readBytes (bytes); maxSize → maxSizeMB; maxAge → maxAgeDays
* `internal/llm/tools/download.go`: maxSize → maxSizeBytes

## [Early bailout](../../definitions/early-bailout.md)

* `internal/logging/recover.go`: prefer early return over wrapping whole body after recover
* `internal/app/lsp_events.go`: use early return instead of wrapping entire body
* `internal/lsp/client.go`: `openKeyConfigFiles` loop guard should use `continue` (file existence)
* `internal/app/app.go`: loop guard should use `continue` (cleanup funcs)
* `internal/shell/shell.go`: `ArgumentsBlocker`: loop guard should use `continue`; avoid wrapping body

Note: Many of these also reduce nesting and overlap with [Minimize nesting](../../definitions/minimize-nesting.md).

## [Minimize nesting](../../definitions/minimize-nesting.md)

* `internal/tui/components/chat/chat.go`: combine nested `if` conditions into one `if` with `&&`
  - ~508–516: combine `asMsg, ok := item.(messages.MessageCmp); ok` + `asMsg.GetMessage().ID == messageID`
  - ~837–841: combine `tc, ok := items[i].(messages.ToolCallCmp); ok` + `tc.Spinning()`
* `internal/message/content.go`: flatten nested type/id/finished guards across helpers
* `internal/app/app.go`: flatten trivial guards in MCP topic derivation
* `internal/lsp/client.go`: `WaitForServerReady`: unnecessary `else` after early return
* `e2e/scenario.go`: combine `E2E_PER_STEP_SECS` read & value check in `NewScenario`
* `internal/pubsub/broker.go`: use short `if` with `s := f.String(); s != "" { ... }`
* `internal/history/file.go`: in `createWithVersion`, flatten nested UNIQUE constraint retry guard

Note: Several of these can also be addressed via guard-clauses; see [Early bailout](../../definitions/early-bailout.md).

## [No one-off vars and trivial wrappers](../../definitions/no-oneoff-vars-and-trivial-wrappers.md)

* `internal/csync/maps.go`: JSONSchemaAlias returns throwaway temp; inline literal
* `internal/format/spinner.go`: inline single-use locals: model, local prog into struct
* `internal/session/session.go`: inline single‑use broker into struct literal
* `internal/config/provider.go` (~82–86): inline one‑off locals:
  - client := catwalk.NewWithURL(...)
  - path := providerCacheFileData()
* `internal/lsp/watcher/watcher.go`:
  * ~568–576: inline one‑off isMatch variable used only for return branch
  * ~653–671, 662–664, 669–672: inline single‑use isMatch temporaries in matchesSimpleGlob

## [No dead code](../../definitions/no-dead-code.md)

- Dead `basePath == ""` guard in `internal/lsp/watcher/watcher.go` (~699–709): the second `if basePath == ""` branch is unreachable; delete it.
- Redundant branch in `View()` in `internal/tui/components/chat/messages/tool.go`: both branches return the same value; remove the conditional and return once.
