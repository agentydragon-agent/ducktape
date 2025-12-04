local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    core.py _extract_message_from_text() (lines 260-263) appears to be unused dead
    code. The function extracts text between <message> tags using regex.

    Project-wide search shows zero usages (only the definition appears). The current
    prompt in build_prompt() instructs the AI to wrap messages in <message> tags,
    but backends don't appear to use this helper for parsing. Extraction was likely
    moved elsewhere or backends parse tags directly.

    Delete the function. Keeping unused code: (1) misleads readers about how
    messages are extracted, (2) clutters the codebase, (3) creates maintenance
    burden, (4) causes doubt about whether it should be called.

    If extraction logic is actually needed, deletion will cause an import error that
    makes the dependency explicit.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/core.py': [
      [260, 263], // _extract_message_from_text: unused function definition
    ],
  },
)
