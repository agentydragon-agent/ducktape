local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    Argparse can directly parse filesystem arguments into pathlib.Path objects by using `type=Path` on add_argument.
    Prefer declaring `ap.add_argument('--foo', type=Path, ...)` so callers receive a Path immediately and avoid scattershot `Path(args.foo)` conversions later.

    Why this matters:
    - Tightens contracts: handlers downstream get the correct type without ad-hoc wrapping.
    - Reduces one-off conversions and improves readability.
    - Avoids small bugs where a string path is treated differently than a Path (e.g., path / os.PathLike handling).
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [[460, 466], [476, 485], [508, 508]],
  },
)
