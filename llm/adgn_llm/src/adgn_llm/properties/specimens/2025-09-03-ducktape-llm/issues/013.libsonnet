local I = import '../../specimens/lib.libsonnet';

// iss-013: Use argparse type=Path for filesystem args to avoid late Path(...) casts
I.issueOneOccurrence(
  rationale=|||
    Argparse can directly parse filesystem arguments into pathlib.Path objects by using `type=Path` on add_argument.
    Prefer declaring `ap.add_argument('--foo', type=Path, ...)` so callers receive a Path immediately and avoid scattershot `Path(args.foo)` conversions later.

    Why this matters:
    - Tightens contracts: handlers downstream get the correct type without ad-hoc wrapping.
    - Reduces one-off conversions and improves readability.
    - Avoids small bugs where a string path is treated differently than a Path (e.g., path / os.PathLike handling).
  |||,
  // properties=['pathlib'],
  gap_note='Design to minimize conversions between different representations (e.g., str<->Path, dict<->Pydantic models, uuid<->str, multiple ad-hoc variables vs one combined structure). Avoid introducing extra conversion surface area that downstream callers must handle.',
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [[564, 573], [572, 575]],
  },
)
