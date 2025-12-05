local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale=|||
    Functions accept collection parameters as Optional, defaulting to None, then
    check for None and convert to empty collection. Should use empty collection
    as default instead.

    Benefits:
    - Simpler type: no Optional/union with None
    - No None checks or reassignments needed
    - Empty tuple is immutable and safe as default
    - Clearer intent: "no items" vs "missing value"
    - Empty collections are falsy if bool check needed

    This is a standard Python idiom for collection parameters.
  |||,
  occurrences=[
    {
      note: 'extra_handlers defaults to None, then converted with `list(extra_handlers or [])`',
      files: {
        'adgn/src/adgn/agent/runtime/local_runtime.py': [
          73,           // extra_handlers: Iterable[BaseHandler] | None = None
          84,           // self._extra_handlers = list(extra_handlers or [])
        ],
      },
      expect_caught_from: [['adgn/src/adgn/agent/runtime/local_runtime.py']],
    },
    {
      note: 'tests defaults to None, then guarded with `if tests:`',
      files: {
        'adgn/src/adgn/agent/policies/scaffold.py': [
          11,           // tests: Sequence[...] | None = None
          21,           // if tests:
        ],
      },
      expect_caught_from: [['adgn/src/adgn/agent/policies/scaffold.py']],
    },
    {
      note: 'attach/detach default to None, then reassigned with `attach or {}` and `detach if detach is not None else []`',
      files: {
        'adgn/src/adgn/agent/persist/sqlite.py': [
          99,           // attach/detach parameters
          [101, 102],   // attach/detach reassignments
        ],
      },
      expect_caught_from: [['adgn/src/adgn/agent/persist/sqlite.py']],
    },
    {
      note: 'Protocol signature uses Optional instead of default empty collection',
      files: {
        'adgn/src/adgn/agent/persist/__init__.py': [
          141,          // patch_agent_specs protocol signature
        ],
      },
      expect_caught_from: [['adgn/src/adgn/agent/persist/__init__.py']],
    },
  ],
)
