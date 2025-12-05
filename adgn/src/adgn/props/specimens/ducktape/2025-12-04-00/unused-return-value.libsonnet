local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Function _commit_all returns str(oid) at line 28, but the return value is unused at all three call sites (lines 47, 50, 54).
    The function should return None since the value is not needed.
    The unnecessary str() conversion loses type information (Oid → str) without any benefit when the value is discarded.
    If future callers need the commit ID, it should return Oid directly (not str).
  |||,
  filesToRanges={'adgn/tests/mcp/git_ro/conftest.py': [[18, 28]]},
)
