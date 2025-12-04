local I = import '../lib.libsonnet';

// iss-028-newline-tab-sanitizer
// Centralize newline/tab sanitization used in Bash command formatting.

I.issue(
  snapshot='crush/2025-08-30-internal_db',
  rationale='Both tool.go and renderer.go perform identical sanitization of Bash command strings (replace "\n" with space and tabs with 4 spaces). Factor into a shared helper (e.g., sanitizeInlineCommand) to avoid duplicated logic and ensure consistent sanitization across UI renderers and copy-to-clipboard output.',
  filesToRanges={
    'internal/tui/components/chat/messages/tool.go': [[276, 280]],
    'internal/tui/components/chat/messages/renderer.go': [[218, 220]],
  },
)
