local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    `_get_editor` shells out via `asyncio.create_subprocess_exec("git", "var", "GIT_EDITOR", ...)` to
    obtain the editor. Prefer using the repo API directly (e.g., `repo.git.var("GIT_EDITOR")`) or a
    config reader fallback (`repo.config_reader().get_value("core", "editor", default)`). This reduces
    subprocess boilerplate and simplifies control flow.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[731, 739]],
  },
)
