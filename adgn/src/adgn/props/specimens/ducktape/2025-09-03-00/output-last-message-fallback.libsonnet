local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The contract of --output-last-message is that the final output exists only in the designated file.
    Falling back to stdout silently violates that contract and can mask real errors.
    More importantly, codex is a TUI app: stdout contains box-drawing and UI noise, so substituting it yields random terminal detritus instead of the model’s final message — and it happens silently with a zero exit code.
    Prefer to fail loudly (or request a new run) if the last message file cannot be read.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[1183, 1191]],
  },
)
