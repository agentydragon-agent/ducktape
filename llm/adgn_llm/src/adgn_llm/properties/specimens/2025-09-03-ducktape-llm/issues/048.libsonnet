local I = import '../../specimens/lib.libsonnet';

// iss-048: Prefer GitPython query over shelling out to `git var`
I.issueOneOccurrence(
  rationale=|||
    `_get_editor` shells out via `asyncio.create_subprocess_exec("git", "var", "GIT_EDITOR", ...)` to
    obtain the editor. Prefer using the repo API directly (e.g., `repo.git.var("GIT_EDITOR")`) or a
    config reader fallback (`repo.config_reader().get_value("core", "editor", default)`). This reduces
    subprocess boilerplate and simplifies control flow.
  |||,
  // properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[731, 739]],
  },
  gap_note='Prefer native repo APIs (repo.git.var / config_reader) instead of shelling out for simple queries.',
)
