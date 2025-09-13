local I = import '../../specimen_issues.libsonnet';

// iss-060: Make COMMAND_NAMES the single source of truth
I.issueOneOccurrence(
  rationale=|||
    Make COMMAND_NAMES the single source of truth and use it in the CLI routing; remove duplicated hardcoded lists in the CLI so routing logic reuses the shared constant.
    - In wt/wt/shared/constants.py: Make COMMAND_NAMES the single source of truth (at lines 4-5).
    - In wt/wt/cli.py: Use COMMAND_NAMES from shared.constants instead of duplicating hardcoded lists in CLI routing (at lines 137-143).
  |||,
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/wt/shared/constants.py': [[4, 5]],
    'wt/wt/cli.py': [[137, 143]],
  },
)
