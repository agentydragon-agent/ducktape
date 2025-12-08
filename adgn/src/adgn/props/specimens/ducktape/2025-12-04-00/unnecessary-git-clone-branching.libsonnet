local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The three branches in `_create_archive_from_git` (bundle files, file:// URLs, and
    remote URLs) execute nearly identical sequences of git operations. All paths end up
    doing the same steps: initialize repository, configure remote, fetch ref, and checkout.

    The branching logic appears to exist to handle bundle files specially and to use
    shallow clones (depth=1) for non-bundle sources. However, this complexity is
    unnecessary because:

    - The optimization of shallow clones is minimal value since these archives are
      cached (one-time operation per commit) and the .git directory is immediately
      deleted anyway
    - Modern git clone can handle all these cases uniformly (bundles, file://, https://)
      without manual init+fetch+checkout steps
    - The duplicated code makes maintenance harder and obscures the actual logic

    The entire function could be simplified to a single `git clone` call that handles
    all source types uniformly, removing ~10 lines of duplicated subprocess invocations.
  |||,
  filesToRanges={ 'adgn/src/adgn/props/snapshot_registry.py': [[363, 393]] },
)
