local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The Jupyter Server configuration string in wrapper.py (lines 277-287) is constructed inline within the _seatbelt function using a local variable jsc. This multi-line configuration string should be moved to a module-level constant with a descriptive SCREAMING_SNAKE_CASE name and docstring.

    A module-level constant like JUPYTER_SERVER_CONFIG_TEMPLATE would improve readability, make the configuration reusable if needed, and clarify its purpose through the name and docstring. The inline comment "keep compact and explicit" (line 277) provides some context but a proper docstring would be more appropriate for a constant.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py': [[277, 287]]},
)
