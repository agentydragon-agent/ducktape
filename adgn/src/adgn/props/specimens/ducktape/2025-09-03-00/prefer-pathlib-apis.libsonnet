local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Prefer using pathlib.Path methods (e.g., Path.exists(), Path.cwd(), Path.is_file()) instead of the older os.path / os.getcwd helpers.

    Benefits:
    - Stronger typing and clearer semantics: callers see Path objects and don't need ad-hoc conversions.
    - Better cross-platform behavior and richer API (methods for joins, parents, resolves, etc.).
    - Reduces repeated str()/Path(...) conversions spread through call sites.

    When migrating, prefer accepting/returning Path objects at API boundaries and use Path.* helpers in implementation.

    Gap note: sometimes it is reasonable to keep values as strings when the entire path value flows as a str through the stack (e.g., an HTTP request param immediately passed to a Docker API that expects strings). The decision is a cost-vs-benefit judgment: use Path where you benefit from pathlib API; avoid needless wrap/unwrap where it buys little.
  |||,
  occurrences=[
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/cli.py': [[340, 343]] },
      note: 'cfg_path computed with Path(..) vs os.path usage; prefer Path APIs',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/cli.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mini_codex/cli.py': [[122, 123]] },
      note: 'cwd handling: prefer Path.cwd()/Path(...) semantics instead of os.getcwd()/os.path',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/cli.py']],
    },
  ],
)
