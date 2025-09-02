## Trivial pass-through wrapper `UpdateAgentModel` is acceptable

Some critiques flagged `app.UpdateAgentModel` as a trivial pass-through that should be inlined (i.e., replace callers with calls to `agent.UpdateModel`).

But actually, squashing this method should NOT be prescribed as required. This method is part of an imperfect facade boundary around App→CoderAgent.
In the context of the facade, it would serve as a decoupling point.
However, the facade is currently imperfect, which is the associated finding that should be reported here.
See correct finding: “App façade vs reach-through”.

## Line numbering for LLM and for human display reported as duplication

- `internal/tui/components/chat/messages/renderer.go`: on-screen TUI display with styled, width-aware numbering for humans.
- `internal/llm/tools/view.go`: in-band plaintext line numbers inside the tool payload (<file>…</file>) for the LLM/log consumers. The TUI typically re-renders from metadata and ignores these in-band numbers.

A critique reported these two as duplication that should be merged. That is a false positive. 
These serve different purposes (human UI vs LLM/plaintext). Different implementations and formatting are appropriate; not duplication.

## CLI flag 'yolo' is acceptable branding

File: `internal/cmd/root.go` (flag defined at lines ~29–31; propagated at ~132–169)

Some critiques suggest renaming `--yolo` and local var `yolo` to a more descriptive predicate (e.g., `--skip-permission-requests`).

This is a false positive: “yolo mode” is a consistent label used across docs/UX, and the help text already clarifies it (“Automatically accept all permissions (dangerous mode)”).
Naming "skip pemissions" as `--yolo` is a valid choice. This is fine as is.

## Over-strict "combine trivial guards / early bailout"

## `internal/fsext/ls.go`

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

## `internal/app/app.go`

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

## `internal/message/message.go`

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
