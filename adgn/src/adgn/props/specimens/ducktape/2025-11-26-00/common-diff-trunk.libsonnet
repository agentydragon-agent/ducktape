local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 130-139 have `repo.diff(...).patch or ""` duplicated in both branches.
    Only the base commit differs. Factor out the common diff call.

    **Current structure:**
    ```
    if head.parents:
        parent = head.parents[0]
        parts.append("=== Original commit diff (HEAD^ to HEAD) ===")
        parts.append(repo.diff(parent.id, head.id).patch or "")
    else:
        empty_tree_oid = repo.TreeBuilder().write()
        parts.append("=== Original commit content ===")
        parts.append(repo.diff(empty_tree_oid, head.id).patch or "")
    ```

    **Better structure:**
    ```
    if head.parents:
        parent = head.parents[0]
        base = parent.id
        parts.append("=== Original commit diff (HEAD^ to HEAD) ===")
    else:
        base = repo.TreeBuilder().write()
        parts.append("=== Original commit content ===")
    parts.append(repo.diff(base, head.id).patch or "")
    ```

    Branches only determine the base commit and header; diff call is common trunk.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [130, 139],  // Duplicated repo.diff call
    ],
  },
)
