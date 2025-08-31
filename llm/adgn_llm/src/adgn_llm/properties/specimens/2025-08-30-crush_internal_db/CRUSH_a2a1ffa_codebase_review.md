# CRUSH (a2a1ffa) Codebase Review – Duplication, Consistency, and Maintainability

- Misc cleanups: minor fold-into-if and guard-clause simplifications; a few magic constants could be centralized (timeouts, line limits, truncation).

### Duplication (top priority)

A15. Repeated metadata wrapping
- File: `internal/llm/tools/tools.go:100-108` (WithResponseMetadata)
- Many tools manually construct metadata structs and wrap similarly; ensure all use WithResponseMetadata; if not, refactor to a single pattern.

### Simplifications (fold-into-if, guard clauses; includes ≥4 concrete before/after)

S6. Fold-into-if for JSON parsing
- Many places use var X; if err := json.Unmarshal(..., &X); err == nil { ... }
  Suggest: if err := json.Unmarshal(..., &X); err != nil { return error } // guard clause
  Example: `internal/tui/components/chat/messages/renderer.go:211-217` (bash.Render) can be written in fold-into-if style, improving readability (many similar cases).

S7. Replace repeated string formatting padding logic
- Example: view.addLineNumbers uses manual width; renderer.getDigits is a more general solution.
  Suggest: reuse a single getDigits/padding approach across both sites.

### Design/Maintainability

D3. Permission/path helpers
- Introduce:
  - ResolvePath(workingDir, p string) (abs string)
  - MustBeInWorkingDirOrRequest(ctx, perms, workingDir, path, toolName, action string, params any) error
  Migrate view/ls/edit/write to these helpers; reduces bugs and normalizes messaging across tools.

D5. Unified “write with history + LSP” flow
- writeFileWithHistory(ctx, filePath, oldContent, newContent, clients, filesSvc) (ToolResponseMetadata, error)
- Use in write tool and all edit branches (create/delete/replace). This collapses 3× near-identical sequences.

D7. Centralize magic constants
- responseContextHeight, MaxReadSize, DefaultReadLimit, MaxLineLength, fetch maxSize, timeout caps, etc. Group under an internal/constants or co-locate per subsystem but import from one place in each subsystem.

## Representative code excerpts (anchors)

- Dual line-numbering:
  `internal/llm/tools/view.go:265-278`
  `internal/tui/components/chat/messages/renderer.go:862-875`
