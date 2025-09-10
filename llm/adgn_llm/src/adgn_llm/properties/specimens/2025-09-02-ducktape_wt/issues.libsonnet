local I = import '../../specimen_issues.libsonnet';

I.rootV2(
  I.sourceGitHub('agentydragon', 'ducktape', '315fe021dbccbbb0682f10954f45d0145c92faf4'),
  I.scope(['wt/**']),
  [

  // iss-001: Imports at the top — many single-line occurrences across files
  I.issueOccurrencesFromLines(
    id='iss-001',
    rationale=|||
     Inline imports inside functions that have no reason to be lazy. Move to module top.
    |||,
    properties=['imports-top'],
    files={
      'wt/wt/cli.py': [101, 158, 193, 198, 206, 253],
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
  ),

  // iss-002: Use StrEnum for string-valued enums
  I.issueOccurrencesFromLines(
    id='iss-002',
    rationale=|||
     Use StrEnum for closed sets of string domain values so they behave as plain strings at boundaries
     (serialization/APIs/JSON) without forcing callers to unwrap .value, while still enforcing the
     allowed set.
    |||,
    properties=['strenum'],
    files={
      'wt/wt/shared/github_models.py': [[13, 18], [49, 52], [60, 62]],
      'wt/wt/shared/configuration.py': [[21, 27]],
      'wt/wt/shared/protocol.py': [[34, 40], [317, 322], [435, 441], [443, 449]],
      'wt/wt/server/gitstatusd_client.py': [[29, 43]],
      'wt/wt/server/copy_strategies.py': [[18, 23]],
    },
  ),

  // iss-003: Markdown inline formatting for identifiers/flags/paths/URIs
  I.issueOccurrencesFromLines(
    id='iss-003',
    rationale=|||
     Bare environment variable identifiers (e.g., WT_DIR) should be formatted as Markdown inline code
     (wrap in backticks).
    |||,
    properties=['inline-formatting'],
    files={
      'wt/ARCHITECTURE.md': [256, 259],
      'wt/WORKTREE_IDEAS.md': [7, 16],
      'wt/tests/README.md': [68, 71],
    },
  ),
  I.issueOccurrencesFromLines(
    id='iss-004',
    rationale=|||
     Environment variables (e.g. PATH) should be formatted as Markdown inline code (i.e., wrap in
     backticks).
    |||,
    properties=['inline-formatting'],
    files={
      'wt/README.md': [16, 18, 190],
    },
  ),

  // iss-005: Pass PathLike to filesystem/subprocess APIs
  I.issueOccurrencesFromLines(
    id='iss-005',
    rationale=|||
     Pass Path/PathLike directly to subprocess and filesystem APIs; avoid unnecessary str().
    |||,
    properties=['pathlike'],
    files={
      'wt/wt/server/copy_strategies.py': [46, 63, 111],
      'wt/wt/server/worktree_service.py': [337],
      'wt/wt/shared/git_utils.py': [29],
      'wt/wt/server/wt_server.py': [2052],
      'wt/tests/repo_factory.py': [172, 188],
    },
  ),
  I.issueOneOccurrence(
    id='iss-006',
    rationale=|||
     `_get_copyable_entries` casts `Path` to `str` while it's used for the purpose of passing into
     `subprocess.run`; should just return unconverted `Path`
    |||,
    properties=['pathlike'],
    files={
        "wt/wt/server/copy_strategies.py": [[12, 15]]
    },
  ),

  // iss-007: Scoped try/except
  I.issueOneOccurrence(
    id='iss-007',
    rationale=|||
     Swallows ImportError/AttributeError silently for plugin loading; at minimum log which entry point
     failed, ideally loudly exit if interactive.
    |||,
    properties=[],
    files={
      'wt/wt/plugins.py': [[59, 63]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-008',
    rationale=|||
     `_refresh_github_cache` swallows exceptions and returns silently in non-boundary code; narrow the
     try to the minimal risky repo access, catch specific exceptions or let them propagate, and log
     appropriately
    |||,
    properties=['scoped-try-except'],
    files={
      'wt/wt/server/wt_server.py': [[586, 593]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-009',
    rationale=|||
     In `PRService.get_pr_info`, a blanket `except Exception` in non-boundary code silently swallows
     errors and the try wraps a long block. Scope the try to just the GitHub call and catch specific
     expected exceptions (or let them propagate) with proper logging.
    |||,
    properties=['scoped-try-except'],
    files={
      'wt/wt/server/wt_server.py': [[613, 635]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-010',
    rationale=|||
     Blanket `except Exception:` sets `git_paths=[]`; do not silently swallow; catch specific expected
     errors (e.g., Git errors) or let propagate, and scope the try narrowly to the list_worktrees call.
    |||,
    properties=['scoped-try-except'],
    files={
      'wt/wt/server/wt_server.py': [[1621, 1624]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-011',
    rationale=|||
     Do not catch case of "fd3 not open/not present" by catching arbitrary OSErrors. In this case,
     positive and explicit probe is not too difficult so should be used: probe fd3 with fcntl
     (F_GETFD/F_GETFL) to verify it exists and is opened for writing.
    |||,
    properties=[],
    files={
      'wt/wt/client/shell_utils.py': [[6, 15]],
    },
  ),

  // iss-012: Forbid dynamic attribute access
  I.issueOccurrencesFromLines(
    id='iss-012a',
    rationale=|||
     `getattr(pygit2, "GIT_STATUS_...", 0)` should be plain `pygit2.GIT_STATUS_...`
    |||,
    properties=['forbid-dynamic-attrs'],
    files={
      'wt/wt/server/git_manager.py': [[116, 123]],
      'wt/wt/server/worktree_service.py': [143],
    },
  ),
  I.issueOneOccurrence(
    id='iss-012b',
    rationale=|||
     pass presets by value (`ConfigPresets.FOO`) instead of by name and `getattr`
    |||,
    properties=['forbid-dynamic-attrs'],
    files={
      'wt/tests/config_factory.py': [[45, 46], 128],
    },
    gap_note='GAP: This also uses dynamic attribute access, but the deeper issue is the name-based pattern itself is brittle. With value-based presets, this code path is unnecessary—no name lookup or error-name formatting needed; prefer value-based API and delete this path. Avoid string→getattr→constant-dict indirection; pass the constant directly (or have the constant hold the config object itself) instead of name-based lookup. ',
  ),

  // iss-013: No dead code — logging_config and duplicate paths
  I.issueOneOccurrence(
    id='iss-013',
    rationale=|||
     logging_config.py: OperationLogger is dead code; JSONFormatter becomes unused once it’s removed.
    |||,
    properties=['no-dead-code'],
    files={
      'wt/wt/shared/logging_config.py': [[31, 94], [8, 29]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-013b',
    rationale=|||
     Duplicate hydration/post-creation script invocation paths: a duplicate implementation exists that’s
     only used by tests; production path is separate and not covered. Consolidate on the prod path.
    |||,
    properties=['no-dead-code'],
    files={
      'wt/wt/server/worktree_service.py': [[98, 164], [299, 380]],
    },
  ),
  I.issueOccurrencesFromLines(
    id='iss-013c',
    rationale=|||
     wt/wt/server/git_manager.py: dead code: `get_status_porcelain`, `status_porcelain`, `rev_count()`;
     `CannotDeleteWorktree` (L40)
    |||,
    properties=['no-dead-code'],
    files={
      'wt/wt/server/git_manager.py': [[40, 41], [200, 224], [310, 312], [313, 315]],
    },
  ),

  // iss-014: Dead code — remove unused classes and helper
  I.issueOccurrencesFromLines(
    id='iss-014',
    rationale=|||
     Dead code declarations in wt_server.py are never used and should be removed.
     Delete StatusSnapshot, WorktreeRuntime, GitStatusdProcess, and _record_github_error helper.
    |||,
    properties=['no-dead-code'],
    files={
      'wt/wt/server/wt_server.py': [[413, 424], [425, 429], [640, 1144], [1230, 1233]],
    },
  ),

  // TODO: add in false_positives.md
])
