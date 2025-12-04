local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    Two adjacent `if known.debug:` blocks perform closely related logging/setup:

      if known.debug:
        print(f"# Resolved model=..., timeout=...", file=sys.stderr)

      if known.debug:
        console_handler = logging.StreamHandler(sys.stderr)
        ...

    Combine them into a single `if known.debug:` to reduce duplicated conditionals,
    group related debug behavior together, and simplify control flow.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[792, 807]],
  },
)
