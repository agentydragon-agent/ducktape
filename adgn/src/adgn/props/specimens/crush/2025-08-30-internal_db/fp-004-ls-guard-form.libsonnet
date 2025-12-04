local I = import '../../lib.libsonnet';

// fp-004-ls-guard-form
// False positive: combining IsDir + ShouldSkip into one guard is not required

I.falsePositive(
  rationale=|||
    A reviewer suggested refactoring the following code in internal/fsext/ls.go
    to combine the nested dir check and skip check into a single condition.

    Original form:
      if d.IsDir() {
          if walker.ShouldSkip(path) {
              return filepath.SkipDir
          }
          return nil
      }

    Suggested combined form:
      if d.IsDir() && walker.ShouldSkip(path) {
          return filepath.SkipDir
      }
      if d.IsDir() {
          return nil
      }

    This is a false positive. Both forms are acceptable; the original nested form
    is equally clear and arguably preferable for readability by making the
    directory-special-case explicit. Do not require this change. If desired,
    lightweight helper extraction (e.g., isDirAndShouldSkip) is fine, but
    forcing this stylistic rewrite is unnecessary.
  |||,
  filesToRanges={
    'internal/fsext/ls.go': [[202, 206]],
  },
)
