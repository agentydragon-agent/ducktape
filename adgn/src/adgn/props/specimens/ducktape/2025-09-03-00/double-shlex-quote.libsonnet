local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 67 has an unnecessarily complex pattern where shlex.quote is applied separately to cmd and each arg:
      " ".join([shlex.quote(cmd), *[shlex.quote(a) for a in args_list]])

    This mixes a list literal containing one quoted item with a spread of a list comprehension that quotes each arg. The duplication of shlex.quote across the two contexts is awkward and harder to read than the unified form:
      " ".join(shlex.quote(x) for x in [cmd, *args_list])

    The unified form applies shlex.quote uniformly to all items (cmd and args) in a single comprehension, making the quoting logic clear and consistent.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [67],
  },
)
