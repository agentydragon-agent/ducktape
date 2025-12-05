local I = import '../../lib.libsonnet';


I.issue(
  rationale='Two near-identical switch statements map file extensions to language names (used for syntax highlighting / clipboard formats) in tool.go. Keep a single mapping table or helper to avoid drift and ensure consistent language naming.',
  filesToRanges={
    'internal/tui/components/chat/messages/tool.go': [[461, 494], [577, 600]],
  },
)
