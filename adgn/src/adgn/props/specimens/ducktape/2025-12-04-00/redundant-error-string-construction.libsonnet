local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Error message construction is duplicated across multiple paths in call_simple_ok.
    The base error message "{name} failed" is constructed separately in the except branch (line 57) and the is_error branch (lines 60-62).
    This can be DRY'd up by constructing the base message once and appending details as needed:
    - Initialize error = f"{name} failed" at the top
    - In except: raise RuntimeError(error + f": {exc}") from exc
    - In is_error check: if detail, append to error; raise RuntimeError(error)
  |||,
  filesToRanges={'adgn/src/adgn/mcp/_shared/client_helpers.py': [[50, 62]]},
)
