local I = import '../../specimens/lib.libsonnet';

// iss-014-filepath-join
// Use filepath.Join instead of string concatenation when composing file paths (dir + "/old", "/new").

I.issueOneOccurrence(
  rationale='Constructing file paths via string concatenation is error-prone (OS path separators) and less idiomatic. Use filepath.Join(dir, "old") / filepath.Join(dir, "new") for portability and clarity.',
  filesToRanges={
    'internal/diff/word_inline.go': [[41, 46], [48, 48]],
  },
)
