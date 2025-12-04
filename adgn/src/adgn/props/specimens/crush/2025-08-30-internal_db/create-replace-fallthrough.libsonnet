local I = import '../../lib.libsonnet';

// iss-026-create-replace-fallthrough
// Create-then-replace fall-through bug in internal/llm/tools/edit.go

I.issue(
  snapshot='crush/2025-08-30-internal_db',
  rationale='When OldString is empty Run() creates the file (createNewFile) but then still falls through and calls replaceContent which treats empty old_string as a literal match, causing "appears multiple times" errors and masking the successful create. Make the branches mutually exclusive (else-if / early return) or otherwise ensure replaceContent is not invoked after a create.',
  filesToRanges={
    'internal/llm/tools/edit.go': [[145, 183], [200, 275], [456, 470]],
  },
)
