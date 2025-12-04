local I = import '../../lib.libsonnet';

// iss-025: Collection parameters should default to empty tuple, not None

I.issue(
  snapshot='ducktape/2025-11-20-00',
  rationale=|||
    Functions accept collection parameters as Optional, defaulting to None, then
    check for None and convert to empty collection.

    Current pattern (local_runtime.py:73,84):
    extra_handlers: Iterable[BaseHandler] | None = None
    self._extra_handlers = list(extra_handlers or [])

    Current pattern (scaffold.py:11,21):
    tests: Sequence[tuple[PolicyRequest, ApprovalDecision]] | None = None
    if tests:
        for idx, (req, expected) in enumerate(tests):

    Current pattern (sqlite.py:99,101-102):
    attach: dict[str, MCPConfig] | None = None, detach: list[str] | None = None
    attach = attach or {}
    detach = detach if detach is not None else []

    Should use empty collection as default:
    extra_handlers: Iterable[BaseHandler] = ()
    self._extra_handlers = list(extra_handlers)

    tests: Sequence[tuple[PolicyRequest, ApprovalDecision]] = ()
    for idx, (req, expected) in enumerate(tests):  # No check needed

    attach: dict[str, MCPConfig] = {}, detach: list[str] = []
    # Use directly, no reassignment

    Benefits:
    - Simpler type: no Optional/union with None
    - No None checks or reassignments needed
    - Empty tuple is immutable and safe as default
    - Clearer intent: "no items" vs "missing value"
    - Empty collections are falsy if bool check needed

    This is a standard Python idiom for collection parameters.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/runtime/local_runtime.py': [
      73,           // extra_handlers: Iterable[BaseHandler] | None = None
      84,           // self._extra_handlers = list(extra_handlers or [])
    ],
    'adgn/src/adgn/agent/policies/scaffold.py': [
      11,           // tests: Sequence[...] | None = None
      21,           // if tests:
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      99,           // attach/detach parameters
      [101, 102],   // attach/detach reassignments
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      141,          // patch_agent_specs protocol signature
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/runtime/local_runtime.py'],
    ['adgn/src/adgn/agent/policies/scaffold.py'],
    ['adgn/src/adgn/agent/persist/sqlite.py'],
    ['adgn/src/adgn/agent/persist/__init__.py'],
  ],
)
