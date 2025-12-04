local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Several functions have docstrings that add no information beyond what the function
    signature already provides. These docstrings are noise and should be deleted.

    **Occurrences:**

    1. **build_handlers (handlers.py:25-27)**
       ```python
       def build_handlers(...) -> tuple[list[BaseHandler], RunPersistenceHandler]:
           """Construct the standard handler stack for an agent.

           Returns (handlers, persist_handler).
           """
       ```
       Problem: The "Returns" line just restates the return type annotation.
       Fix: Delete the "Returns" line, or delete the entire docstring if first line adds no value.

    2. **default_client_factory (app.py:50-52)**
       ```python
       def default_client_factory(model: str) -> OpenAIModelProto:
           """Default LLM client factory."""
           return build_client(model, enable_debug_logging=True)
       ```
       Problem: Docstring just restates the function name. Provides zero additional information.
       Fix: Delete the docstring entirely.

    3. **default_client_factory (container.py:128-129)**
       ```python
       def default_client_factory(model: str) -> OpenAIModelProto:
           """Default LLM client factory used when no custom factory is provided."""
       ```
       Problem: The "when no custom factory is provided" part is slightly useful, but the
       "Default LLM client factory" part is redundant.
       Fix: Could be condensed to just "Used when no custom factory is provided." or deleted.

    **General principle:**
    - Docstrings should add information not obvious from the signature
    - "Returns X" when signature says "-> X" is pure noise
    - Restating the function name in sentence form is useless
    - Keep docstrings only when they explain WHY, not WHAT

    **Benefits of removal:**
    1. Less noise to maintain
    2. Clearer signal-to-noise ratio in codebase
    3. Encourages writing meaningful docstrings when needed
    4. Type annotations already document the "what"
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
