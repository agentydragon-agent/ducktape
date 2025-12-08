local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 184-187 use string operations (str(), .startswith(), string concatenation) to validate that a container path is under WORKING_DIR, then use .removeprefix() on line 189. This should use Path operations instead for type safety and clarity.

    The check should use Path methods like .is_relative_to() or .resolve() with .parents to verify the path is under WORKING_DIR, avoiding string manipulation and the need to add trailing slashes.
  |||,
  filesToRanges={'adgn/src/adgn/props/prompt_optimizer.py': [[184, 187], 189]},
)
