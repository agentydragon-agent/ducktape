local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 136-137 create TreeBuilder, write it, and never use `tb` again. Inline:

    **Current:** `tb = repo.TreeBuilder() ; empty_tree_oid = tb.write()`
    **Fix:** `empty_tree_oid = repo.TreeBuilder().write()`
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [136, 137],  // tb should be inlined
    ],
  },
)
