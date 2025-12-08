local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `_create_archive_from_git` function uses subprocess calls to invoke git commands
    directly (`subprocess.run(["git", "clone", ...])`, `subprocess.run(["git", "init", ...])`,
    etc.), while the rest of the codebase consistently uses pygit2 for git operations.

    Using subprocess for git operations has several drawbacks:
    - Inconsistent with codebase conventions (pygit2 is used elsewhere)
    - No type safety or structured error handling (parsing return codes instead of exceptions)
    - Requires spawning external processes (higher overhead)
    - More brittle (depends on git CLI being available and compatible)

    pygit2 provides a native Python API for git operations including clone, init, remote
    management, fetch, and checkout. The function should be migrated to use pygit2's
    `clone_repository()`, `init_repository()`, `Repository.remotes.create()`,
    `Remote.fetch()`, and `Repository.checkout_tree()` methods.

    This would make the code more maintainable, consistent with project standards, and
    provide better error handling through structured exceptions rather than subprocess
    return codes.
  |||,
  filesToRanges={ 'adgn/src/adgn/props/snapshot_registry.py': [[363, 393]] },
)
