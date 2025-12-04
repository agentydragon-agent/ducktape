local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Several functions have docstrings that add no information beyond what the function
    signature already provides. These are noise.

    **Examples:**
    1. handlers.py:25-27 `build_handlers()`: "Returns (handlers, persist_handler)" just
       restates the return type annotation.
    2. app.py:50-52 `default_client_factory()`: "Default LLM client factory" restates the
       function name with no added value.
    3. container.py:128-129 `default_client_factory()`: "Default LLM client factory used
       when no custom factory is provided" - first part redundant, second part slightly
       useful but could be condensed.

    **Principle:** Docstrings should explain WHY, not WHAT. "Returns X" when signature says
    "-> X" is noise. Restating the function name in prose is useless. Type annotations
    already document the "what".

    **Fix:** Delete useless docstrings entirely. Where partial value exists, condense to
    only the non-redundant part.
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/runtime/handlers.py': [[25, 27]],
      },
      note: 'build_handlers: "Returns" line restates return type',
      expect_caught_from: [['adgn/src/adgn/agent/runtime/handlers.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/server/app.py': [[50, 52]],
      },
      note: 'default_client_factory: useless docstring',
      expect_caught_from: [['adgn/src/adgn/agent/server/app.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/runtime/container.py': [[128, 129]],
      },
      note: 'default_client_factory: mostly useless docstring',
      expect_caught_from: [['adgn/src/adgn/agent/runtime/container.py']],
    },
  ],
)
