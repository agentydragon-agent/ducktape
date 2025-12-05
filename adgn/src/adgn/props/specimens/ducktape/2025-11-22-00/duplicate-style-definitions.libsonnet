local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    AgentsSidebar.svelte line 347 contains a useless historical comment: "Backdrop
    styling moved to ModalBackdrop component". This documents a past refactoring
    rather than explaining current behavior.

    Problems: (1) historical note provides no value to readers, (2) ModalBackdrop's
    existence is already obvious from imports and usage, (3) redundant with "Modal
    styles" section header.

    Delete the comment. Historical notes ("moved to...", "used to be...") clutter
    code without explaining current behavior. Comments should explain complexity,
    workarounds, or non-obvious behavior, not document past refactorings.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[347, 347]],
  },
)
