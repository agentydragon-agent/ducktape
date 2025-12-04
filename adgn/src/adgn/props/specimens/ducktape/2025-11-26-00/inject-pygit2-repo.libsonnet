local I = import '../lib.libsonnet';

// iss-051: Inject pygit2 repository into generate_commit_message_minicodex

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale=|||
    Lines 161-164 discover and create a pygit2 repository inside
    `generate_commit_message_minicodex()`. This violates dependency injection.

    **Current:**
    ```python
    async def generate_commit_message_minicodex(model: str, *, debug: bool = False, amend: bool = False) -> str:
        # Wire an in-proc read-only Git MCP server bound to the current repo
        gitdir = pygit2.discover_repository(Path.cwd())
        assert gitdir, "Unable to locate git repository"
        repo = pygit2.Repository(gitdir)
        repo_root = Path(repo.workdir or Path(gitdir).parent)
        # ... uses repo internally ...
    ```

    **Problems:**
    1. Function creates its own dependencies instead of receiving them
    2. Harder to test - can't inject a test repository
    3. Duplicates repository discovery logic (caller might already have repo)
    4. Tight coupling to current working directory

    **Fix:**
    ```python
    async def generate_commit_message_minicodex(
        repo: pygit2.Repository,
        model: str,
        *,
        debug: bool = False,
        amend: bool = False
    ) -> str:
        """Run MiniCodex with docker_exec + submit_commit_message MCP servers."""
        repo_root = Path(repo.workdir or repo.path).parent
        # ... rest of function ...
    ```

    Caller already has the repo (cli.py:704), so just pass it through.

    **Also refactor:** The MCP server it creates internally should also use this
    injected repository instead of discovering its own.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/minicodex_backend.py': [
      [158, 164],  // Function creates repo instead of receiving it
    ],
  },
)
