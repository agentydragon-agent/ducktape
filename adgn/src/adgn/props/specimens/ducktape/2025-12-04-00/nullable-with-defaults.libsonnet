local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The apply_gitignore_patterns function accepts include and exclude as list[str] | None,
    then checks "if include:" and "if exclude:" at lines 37-42. These parameters should
    instead be Sequence[str] with default=() in the function signature, eliminating the
    need for None checks. This makes the contract clearer and reduces defensive code.
  |||,
  filesToRanges={'adgn/src/adgn/props/cli_app/cmd_build_bundle.py': [[18, 44]]},
)
