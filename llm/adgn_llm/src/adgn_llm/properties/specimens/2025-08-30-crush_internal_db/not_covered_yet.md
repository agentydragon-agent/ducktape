## Duplication

### Resolution of relative/empty path (`internal/llm/tools/{view,write,edit}.go`)

Each tool repeats the same join logic:

```go
if !filepath.IsAbs(filePath) {
    filePath = filepath.Join(workingDir, filePath)
}
```

LS also separately defaults empty path to workingDir. Put both behaviors into a single resolver to avoid 3 copies.

## `internal/llm/tools/write.go` reads same file content twice

Two reads of the same file occur in close succession (oldContent at ~148–151 and again at ~161–167).
Instead read once and reuse for equality check, diff, and history recording.
