local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    Multiple locations build nearly-identical git diff invocations, differing only by a single flag
    (HEAD vs --cached) while repeating common flags like --name-status / --unified=0 / --stat.

    Recommended: compute the common args once and derive the variant:
    - args_common = ["--unified=0"] (or ["--name-status"], ["--stat"]) as applicable
    - head_args = ["HEAD", *args_common]; cached_args = ["--cached", *args_common]
    - For display, join arrays to a printable string; for execution, splat arrays into repo.git.diff(...)

    This removes duplication, reduces drift risk across call sites, and keeps the diff semantics consistent.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [
      [144, 153],
      [187, 193],
      [301, 317],
      [321, 324],
      [343, 346],
      [373, 389],
      [430, 431],
    ],
  },
)
