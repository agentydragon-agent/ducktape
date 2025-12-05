local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The test_db fixture seeds four Prompt records that are never used by any test.
    Lines 257-260 create prompts with sha256 values "test123", "unknown", "test", and
    "train-test", but no test queries or references these values. All tests that use
    the Prompt table either create their own prompts (e.g., test_agent_queries.py
    line 105 creates "a"*64) or call load_and_upsert_detector_prompt() which creates
    its own entries. These seeded prompts should be deleted.
  |||,
  filesToRanges={'adgn/tests/props/conftest.py': [[255, 260]]},
)
