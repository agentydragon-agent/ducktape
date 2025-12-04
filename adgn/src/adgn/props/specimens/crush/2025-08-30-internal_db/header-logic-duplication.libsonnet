local I = import '../../lib.libsonnet';


I.issue(
  rationale='makeHeader and makeNestedHeader in internal/tui/components/chat/messages/renderer.go duplicate the same icon selection, tool styling, and prefix construction logic. Consolidate into a shared helper (or a single function with a flag) to remove copy-paste and make future changes less error-prone.',
  filesToRanges={
    'internal/tui/components/chat/messages/renderer.go': [[117, 136], [137, 158]],
  },
)
