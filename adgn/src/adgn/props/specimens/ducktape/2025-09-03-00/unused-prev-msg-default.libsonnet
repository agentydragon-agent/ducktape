local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The parameter is declared with a default that callers never use:

      previous_message: str | None = None

    Unused defaults add unnecessary degrees of freedom and complicate API contracts.
    Prefer tightening the signature: drop the default (require an explicit value from callers)
    or make the parameter mandatory only where needed via a higher-level object.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[280, 281]],
  },
)
