local I = import '../../lib.libsonnet';

// Merged: redundant-variable-rename, needless-variable-rename
// Both describe unnecessary variable renames that add no clarity

I.issue(
  rationale= |||
    Variables are renamed without adding clarity or semantic meaning.

    Location 1 (runner.py:32): parameter `docker_client` is immediately
    renamed to `client`. No value added - either rename the parameter itself
    or use `docker_client` throughout.

    Location 2 (cli.py:581): `final_text` is renamed to `content_before`,
    but both names mean the same thing. Use the semantic name from the start.

    Problems: extra variables to track, confusion about which name to use,
    more code, cognitive load. Fix: use one consistent name throughout.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/runner.py': [
      [32, 32],  // client = docker_client
    ],
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [581, 581], // content_before = final_text
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/policy_eval/runner.py'],
    ['adgn/src/adgn/git_commit_ai/cli.py'],
  ],
)
