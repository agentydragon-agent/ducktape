local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Multiple test functions duplicate the same config resolution pattern:
      wt_dir = Path(wt_cli.env["WT_DIR"])
      config = Configuration.resolve(wt_dir)
      repo = pygit2.Repository(config.main_repo)

    This violates DRY and should be extracted to pytest fixtures:
    - real_config: provides Configuration object
    - pygit2_repo: provides pygit2.Repository instance

    Tests should depend on these fixtures instead of resolving config inline.
  |||,
  occurrences=[
    {
      files: {'wt/tests/e2e/test_path_watcher_integration.py': [[72, 74]]},
      note: 'First occurrence in test_path_watcher_full_lifecycle',
      expect_caught_from: [['wt/tests/e2e/test_path_watcher_integration.py']],
    },
    {
      files: {'wt/tests/e2e/test_path_watcher_integration.py': [[127, 129]]},
      note: 'Second occurrence in test_path_watcher_multiple_worktrees',
      expect_caught_from: [['wt/tests/e2e/test_path_watcher_integration.py']],
    },
  ],
)
