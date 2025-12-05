local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    Current guard hides misconfiguration and adds branching:

      if not (precommit_path.exists() and precommit_path.is_file()):
        return

    Prefer checking only existence and letting execution surface errors for non-regular files
    (or raise a specific error). This exposes misconfigurations instead of silently skipping
    and reduces control-flow complexity.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[596, 598]],
  },
)
