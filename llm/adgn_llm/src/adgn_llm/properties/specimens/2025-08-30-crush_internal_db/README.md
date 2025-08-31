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

This should be deduplicated. One option:

```go
type ContentPart interface { Type() partType }

var decoders = map[partType]func() ContentPart{
    reasoningType: func() ContentPart { return &ReasoningSummaryContent{} },
    // ... other types
}

// marshal
typ := part.Type()

// unmarshal
if newPart, ok := decoders[wrapper.Type]; ok {
    p := newPart()
    if err := json.Unmarshal(wrapper.Data, p); err != nil { return nil, err }
    parts = append(parts, p)
}
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

### Trivial pass-through wrapper (UpdateAgentModel) is intentional

Some critiques flagged `app.UpdateAgentModel` as a trivial pass-through that should be inlined (i.e., replace callers with calls to `agent.UpdateModel`).

But actually, squashing this method should NOT be prescribed as required. This method is part of an imperfect facade boundary around App→CoderAgent.
In the context of the facade, it would serve as a decoupling point.
However, the facade is currently imperfect, which is the associated finding that should be reported here.
See correct finding: “App façade vs reach-through”.

### Line numbering implementation for LLM and for human display reported as duplication

- `internal/tui/components/chat/messages/renderer.go`: on-screen TUI display with styled, width-aware numbering for humans.
- `internal/llm/tools/view.go`: in-band plaintext line numbers inside the tool payload (<file>…</file>) for the LLM/log consumers. The TUI typically re-renders from metadata and ignores these in-band numbers.

A critique reported these two as duplication that should be merged. That is a false positive. 
These serve different purposes (human UI vs LLM/plaintext). Different implementations and formatting are appropriate; not duplication.

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

Prefer time.Time for timestamps and time.Duration for timeouts/durations (avoid bare ints; if you must use int, suffix units in names).

* `internal/message/content.go`: StartedAt/FinishedAt/CreatedAt/UpdatedAt int64 → time types or unit‑suffixed, Finish.Time int64 lacks unit → time.Time or unit‑suffixed
* `internal/llm/tools/download.go`: maxTimeout → maxTimeoutSecs; Timeout int → TimeoutSecs or time.Duration
* `internal/llm/tools/tools.go`: StartedAt/UpdatedAt int64 are ms epoch; suffix units or use time types
* `internal/llm/tools/fetch.go`: Timeout int is seconds; prefer time.Duration (or suffix with units like TimeoutSecs)
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

## Additional findings (this pass)


### In `internal/tui/components/chat/messages/renderer.go` metadata parse fallback is duplicated

In multiple branches (edit, multi-edit, view) the same pattern repeats:

```go
var meta tools.EditResponseMetadata
if err := er.unmarshalParams(v.result.Metadata, &meta); err != nil {
    return renderPlainContent(v, v.result.Content)
}
```

This is duplicated logic across branches and risks drift; centralize in a small helper.
### In `internal/tui/components/chat/messages/renderer.go` and `internal/tui/components/chat/messages/tool.go` parameter rendering is duplicated

Across the renderer and copy-to-clipboard code, the same per-tool formatting is built repeatedly:

```go
parts = append(parts, fmt.Sprintf("**URL:** %s", params.URL))
parts = append(parts, fmt.Sprintf("**File Path:** %s", fsext.PrettyPath(params.FilePath)))
if params.Timeout > 0 {
    parts = append(parts, fmt.Sprintf("**Timeout:** %s", (time.Duration(params.Timeout)*time.Second).String()))
}
```

This invites inconsistencies between display and copy; use shared helpers/registry.
### In `internal/llm/tools/view.go` and `internal/llm/tools/ls.go` the “outside working dir” gating is duplicated

Both tools perform the same rel-path check and permission request:

```go
relPath, err := filepath.Rel(absWorkingDir, absFilePath)
if err != nil || strings.HasPrefix(relPath, "..") {
    // build permission.CreatePermissionRequest and prompt
}
```

Two copies to maintain increases wording/param drift risk; factor into one helper.
### In `internal/llm/tools/view.go`, `internal/llm/tools/write.go`, and `internal/llm/tools/edit.go` relative path resolution (and empty path) is duplicated

Each tool repeats the same join logic:

```go
if !filepath.IsAbs(filePath) {
    filePath = filepath.Join(workingDir, filePath)
}
```

LS also separately defaults empty path to workingDir. Put both behaviors into a single resolver to avoid 3 copies.
### In `internal/llm/tools/edit.go` and `internal/llm/tools/write.go` the history/LSP bookkeeping is duplicated

The same sequence appears in multiple branches:

```go
file, err := files.GetByPathAndSession(ctx, filePath, sessionID)
if err != nil {
    _, _ = files.Create(ctx, sessionID, filePath, oldContent)
}
if file.Content != oldContent {
    _, _ = files.CreateVersion(ctx, sessionID, filePath, oldContent)
}
_, _ = files.CreateVersion(ctx, sessionID, filePath, newContent)
```

It shows up in deleteContent (~379–400), replaceContent (~518–538), and write.go (~204–224). Extract a helper.
### In `internal/tui/components/chat/messages/tool.go` the extension→language mapping is duplicated

Two near-identical switches (view vs write copy):

```go
switch ext {
case ".go": lang = "go"
case ".py": lang = "python"
// ...
}
```

Keeping them in sync is error-prone; use one mapping.
### In `internal/tui/components/chat/messages/renderer.go` and `internal/tui/components/chat/messages/tool.go` newline/tab sanitization is duplicated

Both sites perform the same replacements:

```go
cmd := strings.ReplaceAll(params.Command, "\n", " ")
cmd = strings.ReplaceAll(cmd, "\t", "    ")
```

Two implementations to maintain risks drift; centralize a sanitizer.
### In `internal/llm/tools/edit.go` the permission/diff/history block is duplicated (3×)

Roughly the same 30+ lines appear in three branches (createNewFile ~226–275, deleteContent ~349–406, replaceContent ~488–550) and include the full sequence:

- `diff.GenerateDiff(oldContent/newContent)`
- Building `permission.CreatePermissionRequest` (Action/Description/Params vary)
- `os.WriteFile(filePath, newContent)`
- history: files.GetByPathAndSession → Create (if missing) → CreateVersion (oldContent) → CreateVersion (newContent)
- recordFileWrite/recordFileRead bookkeeping

These should be centralized behind a helper parameterized by Action, Description, and Params to avoid drift.
### In `internal/tui/components/chat/messages/tool.go` function `View()` has a redundant branch

This function returns the same value in both branches:

```go
if m.isNested {
    return box.Render(content)
}
return box.Render(content)
```

The conditional adds no value; return once.
### In `internal/tui/components/chat/messages/tool.go` method `ToolCallCmp.Spinning()` can be simplified

Current shape:

```go
if m.spinning { return true }
for _, nested := range m.nestedToolCalls {
    if nested.Spinning() { return true }
}
return m.spinning
```

Simplify by early-returning on nested spins, then returning m.spinning.
### In `internal/llm/tools/write.go` the file content is read twice

Two reads of the same file occur in close succession (oldContent at ~148–151 and again at ~161–167); instead read once and reuse for equality check, diff, and history recording.

### In `internal/llm/tools/edit.go` create-then-replace fall-through bug

When `old_string` is empty, `Run` first creates the file, then still calls `replaceContent`, which treats `old_string` literally and errors as “appears multiple times,” masking the successful create.

Skeleton (Run):

```go
// edit.go (Run)
if params.OldString == "" {
    response, err = e.createNewFile(ctx, params.FilePath, params.NewString, call)
    if err != nil { return response, err }
}
if params.NewString == "" {
    response, err = e.deleteContent(ctx, params.FilePath, params.OldString, params.ReplaceAll, call)
    if err != nil { return response, err }
}
response, err = e.replaceContent(ctx, params.FilePath, params.OldString, params.NewString, params.ReplaceAll, call)
```

Skeleton (replaceContent):

```go
// edit.go (replaceContent)
index := strings.Index(oldContent, oldString)         // 0 when old_string == ""
lastIndex := strings.LastIndex(oldContent, oldString) // len(oldContent)
if index != lastIndex {
    return NewTextErrorResponse("old_string appears multiple times ..."), nil
}
```

Behavior: a successful create is followed by an error from `replaceContent`, masking success. Fix: make branches mutually exclusive (else-if, early returns).

### In `fetch.go` and `view.go` UTF-8 variable name typo

Both files use `isValidUt8` (missing "F") for the UTF-8 validity check. Fix typo to `isValidUTF8`.

### In `internal/llm/tools/ls.go` and `internal/llm/tools/edit.go` path schema/docs inconsistent with behavior

- `internal/llm/tools/ls.go`: ToolInfo.Required lists "path" as required, but Run allows empty path and defaults to workingDir (e.g., lines 119–123, 536–543). Inconsistent; schema/docs and behavior should be aligned.
- `internal/llm/tools/edit.go`: Description (lines 48–104) says absolute path only, but Run joins relative paths with workingDir (lines 155–157). Inconsistent; docs and behavior should be aligned.

Same typo in `internal/llm/tools/fetch.go` and `.../view.go`. 

### App façade vs reach-through

App acts as a composition root/lifecycle manager (wires Sessions/Messages/History/Permissions, LSP/MCP, event bus) and also exposes a partial façade over the CoderAgent (e.g., `UpdateAgentModel` pass‑through).
However, the TUI code frequently reaches through `app` to inner services directly (Law of Demeter violation), leading to an inconsistent boundary and a leaky façade.

- Representative reach‑through call sites (non‑exhaustive):
  - `internal/tui/page/chat/chat.go`: `p.app.CoderAgent.IsBusy()`, `p.app.CoderAgent.Run(...)`, `p.app.CoderAgent.Cancel(...)`, direct `p.app.Sessions.Create(...)`
  - `internal/tui/tui.go`: busy checks and model updates via `a.app.CoderAgent`, permissions toggles via `a.app.Permissions`
  - `internal/tui/components/chat/editor/editor.go`: session/agent checks via `m.app.CoderAgent.*`, config/permissions via `m.app.Config()/m.app.Permissions`
- Risks: duplicated “busy” guards across UI, harder refactors of agent/model boundaries, muddled ownership of permission prompts, and drift between façade methods and direct service calls.

Code should choose one strategy and apply it consistently:

1) Strengthen App as a proper façade for the Agent boundary
   - Provide: `IsAgentBusy()`, `RunAgent(ctx, sessionID, text, attachments...)`, `CancelAgent(sessionID)`, `UpdateAgentModel()`, `AgentModel()`
   - Prefer routing all TUI agent interactions through App; optionally make inner agent field private to discourage reach‑through.
   - Keep Sessions/Messages/Permissions either behind light façade utilities (when cross‑cutting behavior exists) or passed as DI consistently.

2) Collapse trivial façade methods and treat App strictly as composition root
   - Remove pass‑throughs like `UpdateAgentModel` if they add no value; access injected services directly everywhere.

Low‑churn pragmatic path: façade only for CoderAgent (busy/run/cancel/model APIs) to unify agent lifecycle/guards, while keeping Sessions/Messages/Permissions as DI.
This would avoid large churn while restoring a clear boundary.
