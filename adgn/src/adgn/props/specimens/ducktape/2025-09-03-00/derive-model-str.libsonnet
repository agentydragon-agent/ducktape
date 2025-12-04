local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    `AppConfig.resolve` constructs `model_str` and also stores `provider` and `model_name` split from it, but
    later code reads the composite `model_str` only for logging/printing. Since `model_str` is trivially derivable
    as `f"{provider}:{model_name}"`, avoid storing this redundant field and derive it where needed.

    This reduces duplicated state and keeps the config focused on primary fields.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[74, 95]],
  },
)
