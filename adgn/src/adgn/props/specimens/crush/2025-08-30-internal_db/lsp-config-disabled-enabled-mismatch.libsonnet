local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    LSPConfig.Disabled field has inverted JSON serialization: the Go field is named `Disabled` but serializes as `"enabled"` in JSON.

    Field definition at internal/config/config.go:127:
    - Go field name: `Disabled bool`
    - JSON tag: `json:"enabled,omitempty"`
    - Schema description: "Whether this LSP server is disabled"

    This creates confusing inverted logic:
    - Setting `{"enabled": true}` in config JSON sets `Disabled = true` in Go (backwards!)
    - Setting `{"enabled": false}` in config JSON sets `Disabled = false` in Go (backwards!)

    The Go code uses `.Disabled` correctly (e.g., internal/tui/components/lsp/lsp.go:63 checks `if l.LSP.Disabled`), so the JSON tag is wrong.

    Fix: Change JSON tag to `json:"disabled,omitempty"` to match the field name and schema description, or rename the Go field to `Enabled` and update the schema description to match.

    This appears to be an incomplete refactoring where the field was partially renamed from one polarity to the other.
  |||,
  filesToRanges={
    'internal/config/config.go': [[127, 127]],
    'internal/tui/components/lsp/lsp.go': [[63, 63]],
  },
  expect_caught_from=[['internal/config/config.go']],
)
