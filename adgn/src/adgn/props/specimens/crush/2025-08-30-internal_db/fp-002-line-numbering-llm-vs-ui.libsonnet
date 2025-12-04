local I = import '../../lib.libsonnet';

// fp-002-line-numbering-llm-vs-ui
// False positive: line-numbering for LLM vs human display are NOT duplication

I.falsePositive(
  rationale=|||
    A past critique reported the LLM-facing in-band plaintext line numbering (internal/llm/tools/view.go)
    and the TUI's styled, width-aware line numbering (internal/tui/components/chat/messages/renderer.go) as
    duplicated functionality deserving consolidation.

    This is a false positive. They serve distinct consumers and purposes: the view tool embeds plain
    numbered lines into the tool payload (for LLM consumption and logs), while the TUI re-renders
    content with visually styled, width-aware numbering optimized for human display. Different
    implementations, formatting, and encoding are appropriate and should be kept separate.

    That said, deduplicating any lower-level helpers that can be safely shared (e.g., a Digits(n int) helper
    for counting decimal digits, or a small utility to normalize line endings) is acceptable and encouraged.
    Keep the surface-level formatting and rendering behavior separate so each consumer can evolve independently.
  |||,
  filesToRanges={
    'internal/llm/tools/view.go': [[258, 276]],
    'internal/tui/components/chat/messages/renderer.go': [[817, 883]],
  },
)
