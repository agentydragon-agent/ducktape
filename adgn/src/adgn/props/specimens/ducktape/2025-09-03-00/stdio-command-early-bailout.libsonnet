local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The `if args.command == "stdio"` branch nests the entire stdio handling flow under an if-block, pushing the main (long) path inside an indented branch.

    Prefer an early-bailout/inverted form that returns or delegates early when the condition isn't met, so the main path is at the base indentation level. This makes long flows easier to read, reduces cognitive load from deep nesting, and shortens diffs when adding or removing steps in the happy path.

    Example: instead of
      if args.command == "stdio":
          # long stdio flow
      else:
          return other_path()
    Prefer
      if args.command != "stdio":
          return other_path()
      # long stdio flow (base indentation)

    Benefits: flatter control flow, clearer happy path, fewer indentation-driven mistakes.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [[475, 475]],
  },
)
