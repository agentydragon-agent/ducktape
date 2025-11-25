local I = import '../../specimens/lib.libsonnet';

// iss-034: LocalAgentRuntime lifecycle confusion and may-be-initialized antipattern

I.issueOneOccurrence(
  rationale= |||
    The `LocalAgentRuntime` class has multiple design issues around lifecycle
    management and initialization patterns:

    **Problem 1: Missing type annotations**

    Parameters `ui_bus` and `connection_manager` lack type annotations, making it
    unclear what types are expected and preventing type checkers from validating
    usage.

    **Current implementation (local_runtime.py, lines 68-84):**
    ```python
    def __init__(
        self,
        running: RunningInfrastructure,
        ...,
        extra_handlers: Iterable[BaseHandler] = (),
        ui_bus=None,                    # ← No type annotation
        connection_manager=None,        # ← No type annotation
    ):
    ```

    **The correct approach:**

    Add proper type annotations:
    ```python
    from adgn.agent.server.runtime import ConnectionManager
    from adgn.agent.notifications.bus import ServerBus

    def __init__(
        self,
        ...,
        ui_bus: ServerBus | None = None,
        connection_manager: ConnectionManager | None = None,
    ):
    ```

    **Problem 2: Confusing lifecycle with incomplete close()**

    The class has `start()`, `run()`, and `close()` methods, but:
    - `close()` only calls `session.cancel_active_run()`
    - `close()` does NOT null out `self.session` or `self.agent`
    - After `close()`, the object is in an invalid state (can't call `run()` again)
    - Unclear if you can call `start()` again after `close()`

    **Current implementation (local_runtime.py, lines 155-172):**
    ```python
    async def run(self, user_text: str) -> AgentResult:
        """Raises RuntimeError if agent not started."""
        if self.agent is None:
            raise RuntimeError("agent not started - call start() first")

        return await self.agent.run(user_text)

    async def close(self) -> None:
        """Does NOT close the underlying RunningInfrastructure.
        Call running.close() separately if needed.
        """
        if self.session is not None:
            await self.session.cancel_active_run()
            # ← session and agent NOT nulled out!
    ```

    **Problems:**

    1. **Incomplete cleanup**: `close()` doesn't null out `self.session`/`self.agent`
    2. **Confusing state**: After `close()`, object looks initialized but isn't usable
    3. **Unclear lifecycle**: Is this single-use or reusable?
    4. **Name trap**: `start()`/`close()` suggests context manager but isn't one
    5. **Inconsistent checking**: `run()` checks `self.agent is None`, not `self.session`

    **Problem 3: "May be initialized" antipattern**

    The class uses nullable fields initialized in `start()`, leading to:
    - Runtime checks (`if self.agent is None: raise RuntimeError`)
    - Type checker confusion (`self.agent` might be `None`)
    - Unclear when object is "ready to use"

    **Current implementation (local_runtime.py, lines 85-88, 155-158):**
    ```python
    def __init__(self, ...):
        ...
        # Initialized by start()
        self.session: AgentSession | None = None
        self.agent: MiniCodex | None = None

    async def run(self, user_text: str) -> AgentResult:
        """Raises RuntimeError if agent not started."""
        if self.agent is None:
            raise RuntimeError("agent not started - call start() first")
        return await self.agent.run(user_text)
    ```

    **Why this is an antipattern:**

    - Object exists but isn't usable (half-initialized state)
    - Every method must check if initialized
    - Type system can't help (fields are `T | None`)
    - Easy to forget to call `start()`
    - Can't use the object after construction

    **Problem 4: Not a proper context manager**

    The class has `start()`/`close()` methods suggesting resource management, but
    doesn't implement `__aenter__`/`__aexit__`, so you can't use `async with`.

    **The correct approach: Make it a proper async context manager**

    Implement `__aenter__`/`__aexit__` to move initialization logic from `start()` into
    the context manager protocol. Store `session` and `agent` as non-nullable fields
    (set in `__aenter__`), eliminating the `if self.agent is None` check in `run()`.

    Benefits: clear lifecycle, type-safe (no nullable fields), idiomatic Python,
    exception-safe cleanup.

    **Alternative: Factory pattern for long-lived objects**

    If context manager doesn't fit, use a classmethod factory like `create()` that
    performs async initialization and returns a fully-initialized instance with
    non-nullable fields. Still cleaner than two-step `__init__` + `start()`.

    **Comparison of approaches:**

    | Approach | Pros | Cons |
    |----------|------|------|
    | Current (`start()`/`close()`) | Explicit control | May-be-initialized, easy to forget |
    | Context manager (`async with`) | Safe, idiomatic | Must use in context |
    | Factory (`create()`) | Explicit, no context needed | Must remember `close()` |

    **When to use which:**

    - **Context manager**: Short-lived resources, clear lifetime
    - **Factory**: Long-lived objects, need flexibility
    - **Two-step init**: Almost never (antipattern)

    **Problem 5: Naming confusion - "run" vs "session"**

    The class has both `session: AgentSession` and a `run()` method. The docstring
    for `close()` says it cancels "active_run" but doesn't explain the relationship
    between "session" and "run". This suggests conceptual confusion.

    **Clarity needed:**

    - A "session" contains multiple "runs"
    - Calling `close()` cancels the current run but leaves the session
    - Or: a "run" is a single interaction, session is the lifetime
    - Document which is which and what cleanup means

    **Summary:**

    1. Add type annotations for `ui_bus` and `connection_manager`
    2. Make class an async context manager (`__aenter__`/`__aexit__`)
    3. Remove `start()` method, move logic to `__aenter__`
    4. Make `session` and `agent` non-nullable (always set in context)
    5. Remove `if self.agent is None` check from `run()`
    6. Implement proper `__aexit__` that nulls out resources
    7. Or: use factory pattern if context manager doesn't fit use case
  |||,
  properties=['proper-resource-management', 'avoid-two-step-initialization', 'type-safe-apis', 'use-context-managers'],
  filesToRanges={
    'adgn/src/adgn/agent/runtime/local_runtime.py': [
      [81, 82],   // Missing type annotations for ui_bus, connection_manager
      [85, 88],   // May-be-initialized antipattern (session/agent nullable)
      [90, 153],  // start() method should be __aenter__
      [155, 158], // run() has unnecessary None check
      [160, 165], // close() doesn't null out session/agent
    ],
  },
  gap_note= |||
    This finding illustrates **"avoid-two-step-initialization"**: classes that
    require calling an initialization method after construction are error-prone
    and hard to type-check.

    Two-step initialization problems:
    - Object exists but isn't usable (half-initialized)
    - Every method needs `if not self._initialized: raise`
    - Type system can't help (fields are `T | None`)
    - Easy to forget initialization step
    - Can't use object immediately after construction

    Better patterns:

    **1. Context manager (for resource management):**
    ```python
    async with Resource(...) as r:
        r.use()  # Always initialized
    ```

    **2. Factory function (when context doesn't fit):**
    ```python
    r = await Resource.create(...)
    r.use()  # Always initialized
    ```

    **3. Builder pattern (for complex configuration):**
    ```python
    r = ResourceBuilder().with_foo(...).with_bar(...).build()
    r.use()  # Always initialized
    ```

    Related to **"proper-resource-management"**: objects that acquire resources
    (connections, sessions, etc.) should either:
    - Be context managers (`async with`)
    - Have clear `create()`/`close()` lifecycle with docs
    - Be single-use (no cleanup needed)

    Related to **"use-context-managers"**: when a class has `start()`/`close()`,
    `open()`/`close()`, or similar pairs, it should usually be a context manager.

    Context manager benefits:
    - Automatic cleanup (guaranteed even on exceptions)
    - Clear lifetime (inside/outside context)
    - Idiomatic (everyone knows `with`/`async with`)
    - Type-safe (resources always set in context)

    Related to **"type-safe-apis"**: missing type annotations force users to
    read implementation or docs to understand expected types. Type checkers
    can't validate usage without annotations.
  |||,
)
