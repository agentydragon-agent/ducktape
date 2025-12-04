local I = import '../lib.libsonnet';

// iss-025-ext-to-lang-mapping
// Deduplicate extension -> language mapping in tool parameter/result formatting (tool.go)

I.issue(
  snapshot='crush/2025-08-30-internal_db',
  rationale='Two near-identical switch statements map file extensions to language names (used for syntax highlighting / clipboard formats) in tool.go. Keep a single mapping table or helper to avoid drift and ensure consistent language naming.',
  filesToRanges={
    'internal/tui/components/chat/messages/tool.go': [[461, 494], [577, 600]],
  },
)
