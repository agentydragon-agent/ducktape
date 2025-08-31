# Specimen: crush/internal/db (behavior snapshot)

- Source repo: agentydragon/crush
- Commit: a2a1ffa00943aa373f688ac05b667083ac3230b1
- Scope: `internal/**`, `e2e/**`, but *NOT* `internal/llm/prompt/**`.
- Date: 2025-08-30

## How to run critic (dry-run)

```bash
adgn-codex-properties find \
    "/Users/mpokorny/code/crush" \
    "all files under internal/db/**" \
    --dry-run \
    --embed-path ../2025-08-29-pyright_watch_report/pyright_watch_report.py \
    --embed-path ../2025-08-29-pyright_watch_report/README.md
```

Parallel runner with 1 critic per subdir: `./scratch/run_parallel_critics.sh`

## My findings

### Duplicated unmarshal+add in `internal/message/message.go`

```go
switch wrapper.Type {
case reasoningType:
    part := ReasoningSummaryContent{}
    if err := json.Unmarshal(wrapper.Data, &part); err != nil {
        return nil, err
    }
    parts = append(parts, part)
case reasoningEncryptedType:
    part := ReasoningEncryptedContent{}
    if err := json.Unmarshal(wrapper.Data, &part); err != nil {
        return nil, err
    }
    parts = append(parts, part)
case textType:
    part := TextContent{}
    if err := json.Unmarshal(wrapper.Data, &part); err != nil {
        return nil, err
    }
    parts = append(parts, part)
// ... N more types
```

This should be deduplicated. I expect Go should have a way of just assigning the right type and doing the "unmarshal + append" all in a shared convergence point at the end.
So something like:

```go
switch wrapper.Type {
case reasoningType:
    part := ReasoningSummaryContent{}
case reasoningEncryptedType:
    part := ReasoningEncryptedContent{}
case textType:
    part := TextContent{}
// ... N more types
if err := json.Unmarshal(wrapper.Data, &part); err != nil {
    return nil, err
}
parts = append(parts, part)
```

### Not-useful "there was dead code here" comment in `e2e/mock_openai_responses.go`:

```go
// deadcode pruned: emitStage1 was unused
```

This seems like a leftover that comments on how the code was edited from a past form. At this point, it is not useful for anything and should be deleted.


### Misleading function name & doc in `renderer.go`

```go
// getFileExtension returns appropriate file extension for syntax highlighting
func (fr fetchRenderer) getFileExtension(format string) string {
	switch format {
	case "text":
		return "fetch.txt"
	case "html":
		return "fetch.html"
	default:
		return "fetch.md"
	}
}
```

This are not a *file extension*. It's a *fake path*. Function should be renamed and doc updated.

### Duplicated styling code in `internal/tui/components/chat/messages/renderer.go`

See `makeNestedHeader` / `makeHeader`:

```go
// makeHeader builds the tool call header with status icon and parameters for a nested tool call.
func (br baseRenderer) makeNestedHeader(v *toolCallCmp, tool string, width int, params ...string) string {
	t := styles.CurrentTheme()
	icon := t.S().Base.Foreground(t.GreenDark).Render(styles.ToolPending)
	if v.result.ToolCallID != "" {
		if v.result.Recovered {
			icon = t.S().Base.Foreground(t.Red).Render(styles.ToolError)
		} else if v.result.IsError {
			icon = t.S().Base.Foreground(t.RedDark).Render(styles.ToolError)
		} else {
			icon = t.S().Base.Foreground(t.Green).Render(styles.ToolSuccess)
		}
	} else if v.cancelled {
		icon = t.S().Muted.Render(styles.ToolPending)
	}
	tool = t.S().Base.Foreground(t.FgHalfMuted).Render(tool)
	prefix := fmt.Sprintf("%s %s ", icon, tool)
	return prefix + renderParamList(true, width-lipgloss.Width(prefix), params...)
}

// makeHeader builds "<Tool>: param (key=value)" and truncates as needed.
func (br baseRenderer) makeHeader(v *toolCallCmp, tool string, width int, params ...string) string {
	if v.isNested {
		return br.makeNestedHeader(v, tool, width, params...)
	}
	t := styles.CurrentTheme()
	icon := t.S().Base.Foreground(t.GreenDark).Render(styles.ToolPending)
	if v.result.ToolCallID != "" {
		if v.result.Recovered {
			icon = t.S().Base.Foreground(t.Red).Render(styles.ToolError)
		} else if v.result.IsError {
			icon = t.S().Base.Foreground(t.RedDark).Render(styles.ToolError)
		} else {
			icon = t.S().Base.Foreground(t.Green).Render(styles.ToolSuccess)
		}
	} else if v.cancelled {
		icon = t.S().Muted.Render(styles.ToolPending)
	}
	tool = t.S().Base.Foreground(t.Blue).Render(tool)
	prefix := fmt.Sprintf("%s %s ", icon, tool)
	return prefix + renderParamList(false, width-lipgloss.Width(prefix), params...)
}
```

Those functions are highly duplicated and should be deduplicated - possibly into a common helper or something else that's appropriate for Go.
(Or could also be one function taking a flag to which they both delegate.)

## False positives

### Over-strict "combine trivial guards / early bailout"

#### `internal/fsext/ls.go`

Reviewer flagged:

> internal/fsext/ls.go: No unnecessary nesting: combine ignore && isDir guard
 
```go
if d.IsDir() {
    if walker.ShouldSkip(path) {
        return filepath.SkipDir
    }
    return nil
}
```

Reviewer flagged this as "combine trivial guards", wanting to write:

```go
if d.IsDir() && walker.ShouldSkip(path) {
    return filepath.SkipDir
}
if d.IsDir() {
    return nil
}
```

This should not have been flagged - either form is fine. (Or arguably even a bit better.)

#### `internal/app/app.go`

In internal/app/app.go:

```go
// Call call cleanup functions.
for _, cleanup := range app.cleanupFuncs {
	if cleanup != nil {
		cleanup()
	}
}
```

This was flagged as "should use early bailout". That's a false positive.
It asked to rewrite:

```go
for _, cleanup := range app.cleanupFuncs {
	if cleanup == nil {
        continue
	}
    cleanup()
}
```

But this rewrite doesn't actually make the code better. It's at best equivalent.
With tiny bodies like this (say like 1-2 lines) directly putting happy path into `if` is fine.

#### `internal/message/message.go`

> internal/message/message.go: Early bailout: use continue instead of wrapping loop body (DeleteSessionMessages)

Original code:

```go
for _, message := range messages {
    if message.SessionID == sessionID {
        err = s.Delete(ctx, message.ID)
        if err != nil {
            return err
        }
    }
}
```

We could save 1 level of depth with a `if message.SessionID != sessionID { continue }`, but the loop is short and early bailout wouldn't remove a lot of pain.
So fine to keep as is, too.

## Confirmed-correct findings from critics

### Names should be descriptive

* `internal/profile/profile.go`: s/v too terse; use address/storedAddr, etc.
* `internal/profile/server.go`: v for CRUSH_PROFILE; pstr for pprof port → clearer names
* `internal/fsext/fileutil.go`: DirTrim params (pwd, lim) should encode meaning/units
* `internal/fsext/ignore_test.go`: oldWd → clearer prev dir name
* `e2e/setup_helpers.go`: `b` nondescriptive name, use e.g. "compressEnabled"
* `internal/session/session.go`: Cost float64 ambiguous; encode currency/scale and prefer fixed‑point

#### Timestamps

* `internal/message/content.go`: StartedAt/FinishedAt/CreatedAt/UpdatedAt int64 → time types or unit‑suffixed, Finish.Time int64 lacks unit → time.Time or unit‑suffixed
* `internal/llm/tools/download.go`: maxTimeout → maxTimeoutSecs; Timeout int → TimeoutSecs or time.Duration
* `internal/llm/tools/tools.go`: StartedAt/UpdatedAt int64 are ms epoch; suffix units or use time types
* `internal/pubsub/broker.go`: now := time.Now().UnixMilli() → time type or nowUnixMs
* `internal/message/message.go`:
  * Watermarks.*TS and Message timestamps → time types or unit‑suffixed
  * Inconsistent units: UpdatedAt set in microseconds without unit suffix
* `internal/history/file.go`: CreatedAt/UpdatedAt int64 → time.Time or unit‑suffixed
* `internal/tui/components/chat/messages/renderer.go`: timeout int seconds → timeoutSeconds or time.Duration
* `internal/session/session.go`: CreatedAt/UpdatedAt int64 → time types or unit‑suffixed
* `internal/transform/transform.go`: CreatedAt int64 → time.Time or explicit unit suffix
* `internal/tui/components/chat/chat.go`: lastUserMessageTime int64 epoch seconds → time.Time or unit‑suffixed

#### IDs

* `internal/message/middleware/debounce.go`: id params represent message IDs → messageID
* `internal/message/middleware/serialized.go`: sessionWorker.id/newSessionWorker(id)/Delete(ctx, id)/op.createSess/op.deleteID → sessionID/messageID
* `internal/message/message.go`: ambiguous id params (interface Delete, Delete(ctx, id string)) → messageID

#### File sizes

* `internal/lsp/watcher/watcher.go`: maxFileSize → maxFileSizeBytes
* `internal/app/app.go`: readBts → readBytes (bytes); maxSize → maxSizeMB; maxAge → maxAgeDays
* `internal/llm/tools/download.go`: maxSize → maxSizeBytes

### Avoid nesting / use early bailout

* `internal/logging/recover.go`: prefer early return over wrapping whole body after recover
* `internal/message/content.go`: flatten nested type/id/finished guards across helpers
* `internal/app/app.go`:
  * early bailout: loop guard should use continue (cleanup funcs)
  * flatten trivial guards in MCP topic derivation
* `internal/app/lsp_events.go`: early bailout: use early return instead of wrapping entire body
* `internal/lsp/client.go`:
  * Early bailout in `openKeyConfigFiles`: loop guard should use continue (file existence)
  * `WaitForServerReady`: unnecessary else after early return
* `e2e/scenario.go`: combine E2E_PER_STEP_SECS read & value check in NewScenario
* `internal/shell/shell.go`: `ArgumentsBlocker`: loop guard in should use continue; avoid wrapping body

### No one-off variables

* `internal/csync/maps.go`: JSONSchemaAlias returns throwaway temp; inline literal
* `internal/format/spinner.go`: inline single-use locals: model, local prog into struct
* `internal/session/session.go`: inline single‑use broker into struct literal

### Other

* `internal/shell/shell.go`: `ArgumentsBlocker`: use labeled continue instead of sentinel flag in inner loop
* `internal/pubsub/broker.go`: No unnecessary nesting/one‑off vars: use short if with s := f.String(); s != "" { ... }
* `internal/diff/word_inline.go`: Use `filepath.Join` instead of string concatenation for paths (`dir + "/old"` and `"/new"`)
* `internal/history/file.go`: No unnecessary nesting: in `createWithVersion`, flatten nested UNIQUE constraint retry guard
