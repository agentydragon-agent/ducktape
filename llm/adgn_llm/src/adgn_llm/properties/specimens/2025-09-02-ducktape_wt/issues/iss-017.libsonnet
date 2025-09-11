local I = import '../../specimen_issues.libsonnet';

  // iss-017: No dead code — unused error types and wrappers
  I.issueOccurrencesFromLines(
    id='iss-017',
    rationale='Dead error types and error-handling helpers add API surface without callers; remove them.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/shared/error_handling.py': [
        [23, 24, 'WorktreeNotFoundError'],
        [27, 28, 'WorktreeAlreadyExistsError'],
        [31, 32, 'ProcessCheckError'],
        [43, 61, 'handle_git_errors'],
        [76, 100, 'handle_process_errors'],
        [102, 117, 'convert_to_click_exception'],
        [120, 139, 'safe_execute'],
      ],
    },
  )
