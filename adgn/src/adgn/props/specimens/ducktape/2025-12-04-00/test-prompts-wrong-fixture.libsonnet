local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 256-260 create test prompts inline in the fixture with invalid prompt_sha256 values
    ("test123", etc. are not valid SHA256 hashes) and mocked text instead of using the proper
    hash_and_upsert_prompt helper which would compute correct SHA256 hashes.

    These should either be moved to dedicated prompt fixtures with proper SHA256 calculation,
    or deleted if not actually needed by tests.
  |||,
  filesToRanges={
    'adgn/tests/props/conftest.py': [[256, 260]],
  },
)
