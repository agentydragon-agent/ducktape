## Overuse of nil-pointer config checks in call sites

Many call sites defensively chain pointer checks like `cfg != nil && cfg.Options != nil && cfg.Options.Diff != nil ...`, which is noisy.

Representative examples:
- `internal/diff/external.go`:41–43, 92–93 (`Diff.ExternalCommand/ParseMode`)
- `internal/lsp/watcher/watcher.go`: numerous `cfg.Options.DebugLSP` and LSPIgnore checks
- `internal/llm/tools/*`: Grep timeout, Bash blocked commands, max tool output size

Centralize nil handling with zero-safe helpers on Config and small package-level wrappers for the global config singleton. Alternatively, use explicit dependency injection: pass *config.Config where needed and call the nil-safe receiver helpers directly; skip package-level wrappers if you want to avoid global reads.
- Add methods (nil-receiver safe):
  - `func (c *Config) DiffOptions() DiffOptions`
  - `func (c *Config) Debug() bool`; `func (c *Config) DebugLSP() bool`
  - Similarly: `{Grep,MCP}Timeout(Secs)`, `MaxToolOutputBytes`, `BashBlockedCommands`, ...
- Either:
  - Add package-level wrappers that read `config.Get()` safely (e.g., `config.DebugLSP()`, `config.Diff()`).
  - Provide `config.CurrentLSPIgnore(name string) *IgnoreSet` that returns a working IgnoreSet even pre-Init (fallback to cwd).
- Or:
  - Refactor to DI the `Config` instead of having package-global singleton
- Refactor call sites to use helpers; e.g.,

Before:
```go
cfg := config.Get()
if cfg != nil && cfg.Options != nil && cfg.Options.Diff != nil && cfg.Options.Diff.ParseMode != "" {
    mode = cfg.Options.Diff.ParseMode
}
```
After:
```go
mode := config.Diff().ParseMode
```

This reduces indentation in hot paths, removes scattered pointer chains and branches and consolidates defaults while being Go-idiomatic.

## Duplication

### Unmarshal+add in `internal/message/message.go`

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

### Styling code in `internal/tui/components/chat/messages/renderer.go`

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

### Deduplicate glob matching (use doublestar across codebase)

Code uses two different implementations of glob matching:

* Custom matching in `internal/lsp/watcher/watcher.go` (`matchesGlob`, `matchesSimpleGlob`)
* `doublestar.Match` used in `internal/fsext/fileutil.go`

Standardize on one implementation, prefer `doublestar` (seems to be a well-maintained implementation), assuming it covers required glob semantics; otherwise document the chosen behavior or isolate matching behind a small helper.

### Line number digit counting

Duplication exists in digit-width calculation:
- `internal/llm/tools/view.go:addLineNumbers` (~258–280) uses a fixed 6-character width via fmt formatting.
- `internal/tui/components/chat/messages/renderer.go:renderCodeContent` (~817–883) computes dynamic width using a `getDigits` helper.

One possible deduplication: extract shared helper (e.g., `internal/format/lineno`) for digit counting:
- `Digits(n int) int`  // number of decimal digits (handles 0 and negatives)

The print format (`fmt.Sprintf("%%%dd", width)`) is also duplicated, but may be kept duplicated - it's only a small piece of code.

Despite the duplication, these implementations should be kept separate and not fully merged. See: "Line numbering for LLM and for human display reported as duplication".

### "Text + metadata" tool response wrapping

Many tools repeat this wrapping pattern with different strings and metadata structs:

```go
return WithResponseMetadata(NewTextResponse(text), SomeResponseMetadata{ /* tool-specific */ }), nil
```

Examples:
- `view.go` (ViewResponseMetadata)
- `ls.go` (LSResponseMetadata)
- `write.go` (WriteResponseMetadata)
- `edit.go` (EditResponseMetadata)
- `multiedit.go` (MultiEditResponseMetadata)
- `grep.go` (GrepResponseMetadata).

Note: `download`, `fetch`, `diagnostics`, `sourcegraph` tools still return bare NewTextResponse.

One possible refactor:
- `tools.go` helper `WrapTextWithMeta(text string, meta any) (ToolResponse, error)` to centralize the wrap and remove nested calls
- Per-tool unexported helpers (in each tool file):
```go
// view.go
func newViewResult(output, filePath, content string) (ToolResponse, error) {
   return WrapTextWithMeta(output, ViewResponseMetadata{FilePath: filePath, Content: content})
}
```

This keeps metadata local to each tool and eliminates duplicated call shape everywhere.

### Metadata parse fallback

In `internal/tui/components/chat/messages/renderer.go`, multiple branches (edit, multi-edit, view) repeat the same pattern:

```go
var meta tools.EditResponseMetadata
if err := er.unmarshalParams(v.result.Metadata, &meta); err != nil {
    return renderPlainContent(v, v.result.Content)
}
```

This is duplicated logic across branches and risks drift; centralize in a small helper.

### Parameter rendering (`internal/tui/components/chat/messages/{renderer,tool}.go`)

Across the renderer and copy-to-clipboard code, the same per-tool formatting is built repeatedly:

```go
parts = append(parts, fmt.Sprintf("**URL:** %s", params.URL))
parts = append(parts, fmt.Sprintf("**File Path:** %s", fsext.PrettyPath(params.FilePath)))
if params.Timeout > 0 {
    parts = append(parts, fmt.Sprintf("**Timeout:** %s", (time.Duration(params.Timeout)*time.Second).String()))
}
```

Centralize in shared helpers for common parts/registry for tools.

### “Outside working dir” gating (`internal/llm/tools/{view,ls}.go`)

Both tools perform the same rel-path check and permission request:

```go
relPath, err := filepath.Rel(absWorkingDir, absFilePath)
if err != nil || strings.HasPrefix(relPath, "..") {
    // build permission.CreatePermissionRequest and prompt
}
```

Factor into one helper.

### Resolution of relative/empty path (`internal/llm/tools/{view,write,edit}.go`)

Each tool repeats the same join logic:

```go
if !filepath.IsAbs(filePath) {
    filePath = filepath.Join(workingDir, filePath)
}
```

LS also separately defaults empty path to workingDir. Put both behaviors into a single resolver to avoid 3 copies.

### History/LSP bookkeeping (`internal/llm/tools/{edit,write}.go`)

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

It shows up in deleteContent (379–400), replaceContent (518–538), and write.go (204–224). Extract a helper.

### Extension→language mapping (`internal/tui/components/chat/messages/tool.go`)

Two near-identical switches (view vs write copy):

```go
switch ext {
case ".go": lang = "go"
case ".py": lang = "python"
// ...
}
```

Keeping them in sync is error-prone; use one mapping.

### Newline/tab sanitization (`internal/tui/components/chat/messages/{renderer,tool}.go`)

Both sites perform the same replacements:

```go
cmd := strings.ReplaceAll(params.Command, "\n", " ")
cmd = strings.ReplaceAll(cmd, "\t", "    ")
```

Two implementations to maintain risks drift; centralize a sanitizer.

### Permission/diff/history block (3×, `internal/llm/tools/edit.go`)

Roughly the same 30+ lines appear in three branches (`createNewFile` 226–275, `deleteContent` 349–406, `replaceContent` 488–550) and include the full sequence:

- `diff.GenerateDiff(oldContent/newContent)`
- Building `permission.CreatePermissionRequest` (Action/Description/Params vary)
- `os.WriteFile(filePath, newContent)`
- history: files.GetByPathAndSession → Create (if missing) → CreateVersion (oldContent) → CreateVersion (newContent)
- recordFileWrite/recordFileRead bookkeeping

These should be centralized behind a helper parameterized by Action, Description, and Params to avoid drift.

## Not-useful "there was dead code here" comment in `e2e/mock_openai_responses.go`:

```go
// deadcode pruned: emitStage1 was unused
```

This seems like a leftover that comments on how the code was edited from a past form. At this point, it is not useful for anything and should be deleted.

## Code can be shorter at no readability cost

### JSON parsing with fold-into-if (guard clause)

Many sites use the pattern `if err := json.Unmarshal(...); err == nil { ... }` and then conditionally build args.
Prefer a guard clause that fails fast on bad input, then proceed on the happy path.
This applies to all of these in `internal/tui/components/chat/messages/renderer.go` except the Bash renderer (which already uses the guard-clause style):

- `editRenderer.Render` (~290–297)
- `multiEditRenderer.Render` (~335–344)
- `writeRenderer.Render` (~384–390)
- `fetchRenderer.Render` (~410–416)
- `downloadRenderer.Render` (~457–463)
- `globRenderer.Render` (~483–488)
- `grepRenderer.Render` (~508–515)
- `lsRenderer.Render` (~535–543)
- `sourcegraphRenderer.Render` (~563–569)

##### Example (`multiEditRenderer.Render`)

**Before**
```go
var params tools.MultiEditParams
var args []string
if err := mer.unmarshalParams(v.call.Input, &params); err == nil {
    file := fsext.PrettyPath(params.FilePath)
    editsCount := len(params.Edits)
    args = newParamBuilder().
        addMain(file).
        addKeyValue("edits", fmt.Sprintf("%d", editsCount)).
        build()
}
```

**After** (guard clause)
```go
var params tools.MultiEditParams
var args []string
if err := mer.unmarshalParams(v.call.Input, &params); err != nil {
    return mer.renderError(v, "Invalid multi-edit parameters")
}
file := fsext.PrettyPath(params.FilePath)
editsCount := len(params.Edits)
args = newParamBuilder().
    addMain(file).
    addKeyValue("edits", fmt.Sprintf("%d", editsCount)).
    build()
```

### `ToolCallCmp.Spinning()` in `internal/tui/components/chat/messages/tool.go`

Current shape:

```go
if m.spinning { return true }
for _, nested := range m.nestedToolCalls {
    if nested.Spinning() { return true }
}
return m.spinning
```

Simplify by early-returning on nested spins, then returning m.spinning.

### Other minor shortenings/simplifications

* `internal/config/config.go` (~166–176): collapse double blank lines in Options; keep at most one between logical groups. If you want a Tool options section, format the comment as a header (e.g., `// ---- Tool options ----`) and keep exactly one blank line above it; otherwise omit the extra blank line.
* `internal/shell/shell.go`: `ArgumentsBlocker`: use labeled continue instead of sentinel flag in inner loop

## Magic constants should be named

Hardcoded timeouts/intervals/limits appear without named constants, making tuning and consistency harder. Name them and centralize per subsystem.

- `internal/lsp/client.go`
  - `ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)` (around line 243) → `const LSPStopTimeout = 5 * time.Second`
  - `ctx, cancel := context.WithTimeout(ctx, 30*time.Second)` (around line 313) → `const LSPWaitReadyTimeout = 30 * time.Second`
  - `time.NewTicker(500 * time.Millisecond)` (around line 317) → `const LSPReadyPollInterval = 500 * time.Millisecond`
  - `maxFilesToOpen := 5` (around line 524) → `const MaxFilesToOpen = 5`
- `internal/diff/external.go`:
  - `context.WithTimeout(..., 2*time.Second)` (around lines 56–63) → `const ExternalDiffTimeout = 2 * time.Second`
- `internal/lsp/diagnostics_wait.go`: 5s diagnostics deadline; 100ms poll interval
- `internal/app/lsp.go`: 30s init timeout; 5s shutdown timeout
- `internal/app/app.go`: 30ms debounce; 2s select timeout; 100ms slow‑op threshold; 5s shutdown timeout
- `internal/lsp/watcher/watcher.go`:
  * 300ms debounceTime (file system events)
  * default recursive max watched dirs = 5000
  * watch mode default string "recursive"
- `internal/llm/agent/sequence_transformer.go`: 1500ms overall deadline; 50ms sleep; 2500ms per‑call timeout
- `internal/llm/agent/agent.go`: 50ms delayed flush; 5s overall timeout; 200ms retry sleep
- `internal/llm/tools/sourcegraph.go`: HTTP client Timeout 30s; IdleConnTimeout 90s

Define named constants for these values (or, alternatively, make them configuration options where useful and worth it).

## `internal/llm/tools/write.go` reads same file content twice

Two reads of the same file occur in close succession (oldContent at ~148–151 and again at ~161–167); instead read once and reuse for equality check, diff, and history recording.

## Create-then-replace fall-through bug in `internal/llm/tools/edit.go`

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



## App façade vs reach-through

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

## Other

* `internal/diff/word_inline.go`: Use `filepath.Join` instead of string concatenation for paths (`dir + "/old"` and `"/new"`)
