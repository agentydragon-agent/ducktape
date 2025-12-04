local I = import '../../lib.libsonnet';

// iss-021: Import statement inside function should be at module top

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale=|||
    Line 70 has `import os` inside the `find_presets()` function. Python imports
    should be at module top, not inside functions.

    **Fix:** Move `import os` to line 3 (after `from __future__ import annotations`).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/presets.py': [
      70,  // import os inside function
    ],
  },
)
