local I = import '../../specimens/lib.libsonnet';

// iss-024: Duplicated agent info construction and thin wrapper methods

I.issueOneOccurrence(
  rationale= |||
    The code has two problems in server.py:

    **Problem 1: Duplicated agent info construction**

    Both `list_agents()` and `get_agent_info()` build the same `AgentInfo` object with identical
    logic (determine run phase, check mode, build capabilities), but the implementation is
    duplicated line-by-line instead of extracting a shared helper (server.py, lines 252-302).

    **The correct approach:**
    Extract a `_build_agent_info(agent_id, agent)` helper method and call it from both resources.
    Alternatively, have `list_agents` call `get_agent_info` for each agent.

    **Problem 2: Thin wrapper methods**

    Methods `get_infrastructure()`, `get_agent_mode()`, and `get_local_runtime()` are trivial
    wrappers that just call `_get_agent_or_raise()` and access one field (server.py, lines 187-198).

    **The correct approach:**
    Let callers use `_get_agent_or_raise()` directly and access fields themselves
    (`agent.running`, `agent.mode`, `agent.local_runtime`). Or if public access is needed,
    rename `_get_agent_or_raise` to `get_agent` and let callers access fields directly.

    **Benefits:**
    1. Less code duplication (single agent info construction)
    2. Easier maintenance (one place for changes)
    3. Simpler API (fewer methods, clearer responsibilities)
    4. More direct (no unnecessary jumps between wrapper methods)
    5. Better testability (can test helper independently)

    **Why thin wrappers are harmful:**
    They add noise without meaningful abstraction, increase maintenance burden, and make it harder
    to see what's actually being accessed.
  |||,
  properties=['avoid-duplication', 'avoid-thin-wrappers'],
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [252, 279],  // list_agents duplicates agent info construction
      [285, 302],  // get_agent_info has same logic
      [187, 198],  // Thin wrapper methods (get_infrastructure, get_agent_mode, get_local_runtime)
    ],
  },
  gap_note= |||
    This finding illustrates **"avoid-thin-wrappers"**: don't create trivial wrapper
    methods that just forward to another method and access one field. These add noise
    without adding value.

    When to avoid wrappers:
    - Single field access (`return self.foo.bar`)
    - Single method call with no logic (`return self.foo.baz()`)
    - No additional validation, transformation, or error handling
    - Doesn't hide complexity or provide meaningful abstraction

    When wrappers ARE appropriate:
    - Converting between representations (e.g., `to_json()`, `to_dict()`)
    - Adding cross-cutting concerns (logging, metrics, authorization)
    - Adapting an interface for a specific use case
    - Providing backwards compatibility during refactoring
    - Hiding complex initialization or validation logic

    The test: if removing the wrapper and inlining it would make code clearer,
    the wrapper is probably unnecessary.

    Examples of bad wrappers:
    ```python
    def get_name(self): return self.person.name
    def is_active(self): return self.status == Status.ACTIVE
    def get_config(self): return self._config
    ```

    Better approach - let callers access directly:
    ```python
    # Instead of wrapper methods, just:
    person = self.get_person()  # meaningful operation
    name = person.name  # direct access
    ```

    Related to **"avoid-duplication"**: this finding also shows duplicated logic
    for building AgentInfo. The duplication could be eliminated by either extracting
    a helper method or having list_agents call get_agent_info.
  |||,
)
