local I = import '../../specimen_issues.libsonnet';

// iss-001: Imports at the top — many single-line occurrences across files
I.issueOccurrencesFromLines(
  rationale='Inline imports inside functions that have no reason to be lazy. Move to module top.',
  properties=['imports-top'],
  linesByFile={
    'wt/wt/cli.py': [101, 137, 143, 158, 193, 198, 206, 253],
    'wt/wt/client/handlers.py': [10, 16, 50, 75, 86, 89, 94, 97, 104, 120, 127, 134, 136, 142, 152, [164, 168], 194, 196, 201, 214, 220, 226, 238, 240, [242, 243], 249, 254, 263, 277, 298, [301, 302], 310, 342],
    'wt/wt/client/shell_utils.py': [9, 20],
    'wt/wt/client/worktree_utils.py': [83, [108, 109], 148],
    'wt/wt/client/wt_client.py': [42, 67, 99, 168],
    'wt/wt/server/github_client.py': [109],
    'wt/wt/server/copy_strategies.py': [123, 139],
    'wt/wt/plugins.py': [41, 46],
    'wt/wt/server/worktree_service.py': [105, 197, 214, 264, 281, 293, [300, 301], 388, 445, 490, 507, 513],
    'wt/wt/server/wt_server.py': [85, 102, 1149, 1171, 1186, 1217, 1240, 1608, 1736, 1741, 1815, 1864, [1884, 1888], 1996, 2021, 2103, 2117, 2155, [2583, 2587]],
    'wt/wt/shared/configuration.py': [69],
    'wt/wt/shared/error_handling.py': [141],
    'wt/tests/e2e/test_path_watcher_integration.py': [23, 60],
    'wt/tests/integration/test_shell_integration.py': [41, 42, 57, 63, 64, 66],
    'wt/tests/test_utils.py': [10, 15],
    'wt/tests/repo_factory.py': [165],
    'wt/tests/conftest.py': [109, 111, 212, 217, 296, 354],
  },
)
