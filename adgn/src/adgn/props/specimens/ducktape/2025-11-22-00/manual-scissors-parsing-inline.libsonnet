local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    cli.py lines 601-609 contain complex scissors+comment filtering logic buried
    inline: splitlines, loop with startswith checks for scissors_mark and "#",
    accumulate result_lines, join.

    Problems: (1) hard to read (mixes control flow with scissors parsing), (2) hard
    to test independently, (3) not reusable (must duplicate if needed elsewhere),
    (4) clutters main function logic.

    Extract to helper function extract_commit_content(text, scissors_mark) that
    returns filtered string. Main function calls: final_content =
    extract_commit_content(edited_content, scissors_mark).

    Benefits: Single responsibility, testable independently, reusable, clearer main
    function logic, can document edge cases in helper docstring.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [601, 609],  // Manual scissors+comment parsing
    ],
  },
)
