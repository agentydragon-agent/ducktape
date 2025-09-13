local I = import '../../specimens/lib.libsonnet';

// iss-005: Pass PathLike to filesystem/subprocess APIs
I.issueOccurrencesFromLines(
  rationale='Pass Path/PathLike directly to subprocess and filesystem APIs; avoid unnecessary str().',
  // properties=['pathlike'],
  linesByFile={
    'wt/wt/server/copy_strategies.py': [46, 63, 111],
    'wt/wt/server/worktree_service.py': [337],
    'wt/wt/shared/git_utils.py': [29],
    'wt/wt/server/wt_server.py': [2052],
    'wt/tests/repo_factory.py': [172, 188],
  },
)
