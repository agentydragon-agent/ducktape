local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The config stores a redundant composite `model_str` solely for a debug print, while `provider` and `model_name` already exist.
    Prefer printing provider and model_name directly (e.g., `provider=..., model=...`) and drop `model_str`.
    If a composite is ever needed, derive `f"{provider}:{model_name}"` at the point of use.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[74, 95]],
  },
)
