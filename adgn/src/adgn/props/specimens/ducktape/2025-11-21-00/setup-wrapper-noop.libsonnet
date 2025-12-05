local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 578-585 define _setup_wrapper() as an explicit no-op "kept for future
    extensibility." Docstring says functionality works without this method. Line
    519 calls it once. This is a YAGNI violation.

    **Why delete:**
    - Explicit no-op with no current value
    - Speculative "future extensibility" - may never be needed
    - Single caller doing nothing useful
    - Maintenance burden and misleading to readers
    - Git history preserves deleted code if needed later

    **What to delete:**
    1. Method definition (lines 578-585)
    2. Call site (line 519): await self._setup_wrapper()
    3. Update comment at line 518 which becomes incorrect

    **Benefits:** Less code, no misleading no-ops, clearer control flow.
  |||,
  filesToRanges={
    'adgn/src/adgn/inop/runners/containerized_claude.py': [
      [578, 585],  // _setup_wrapper no-op method definition
      [519, 519],  // Call site to delete
      [518, 518],  // Comment that becomes incorrect after deletion
    ],
  },
)
