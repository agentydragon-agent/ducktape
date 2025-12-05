local I = import '../../lib.libsonnet';

I.issue(
  expect_caught_from=[
    ['llm/adgn_llm/src/adgn_llm/mini_codex/agent.py'],
    ['llm/adgn_llm/src/adgn_llm/mini_codex/cli.py'],
  ],
  rationale=|||
    `_responses_create_with_retry` is duplicated in mini_codex/agent.py and mini_codex/cli.py. Define it once
    (e.g., in agent.py) and import in the CLI to avoid drift and keep retry policy centralized.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/agent.py': [[42, 42]],
    'llm/adgn_llm/src/adgn_llm/mini_codex/cli.py': [[184, 185]],
  },
)
