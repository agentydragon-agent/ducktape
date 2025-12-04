local I = import '../../lib.libsonnet';

// iss-034: LocalAgentRuntime lifecycle confusion and may-be-initialized antipattern

I.issue(
  rationale= |||
    `LocalAgentRuntime` has lifecycle and initialization issues: missing type annotations,
    incomplete cleanup, "may be initialized" antipattern, and not being a proper context
    manager despite `start()`/`close()` methods.

    **Problems:**

    | Issue | Lines | Impact |
    |-------|-------|--------|
    | Missing type annotations | 81-82 | `ui_bus`, `connection_manager` untyped |
    | May-be-initialized antipattern | 85-88 | `session`/`agent` nullable, runtime checks |
    | Incomplete cleanup | 160-165 | `close()` doesn't null fields |
    | Not a context manager | - | Has `start()`/`close()` but no `__aenter__`/`__aexit__` |
    | Runtime checks | 155-158 | `if self.agent is None: raise RuntimeError` |

    **Impact of "may be initialized" antipattern:**
    - Object exists but isn't usable (half-initialized)
    - Every method must check if initialized
    - Type system can't help (fields are `T | None`)
    - Easy to forget `start()` call

    **Solution 1: Async context manager (preferred)**

    ```python
    async def __aenter__(self):
        # Move start() logic here
        self.session = ...  # Set non-nullable fields
        self.agent = ...
        return self

    async def __aexit__(self, ...):
        if self.session:
            await self.session.cancel_active_run()
        self.session = None
        self.agent = None

    async def run(self, user_text: str) -> AgentResult:
        # No None check needed - always initialized in context
        return await self.agent.run(user_text)
    ```

    **Solution 2: Factory pattern**

    ```python
    @classmethod
    async def create(...) -> LocalAgentRuntime:
        instance = cls.__new__(cls)
        # Perform async init
        instance.session = ...  # Non-nullable
        instance.agent = ...
        return instance
    ```

    **Comparison:**

    | Approach | Lifecycle | Type safety | Cleanup |
    |----------|-----------|-------------|---------|
    | Current | Manual, unclear | Weak (nullable) | Incomplete |
    | Context manager | Automatic, clear | Strong | Guaranteed |
    | Factory | Manual | Strong | Manual |

    **Additional fixes:**
    1. Add type annotations: `ui_bus: ServerBus | None`, `connection_manager: ConnectionManager | None`
    2. Document session vs run relationship
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/local_runtime.py': [
      [81, 82],   // Missing type annotations for ui_bus, connection_manager
      [85, 88],   // May-be-initialized antipattern (session/agent nullable)
      [90, 153],  // start() method should be __aenter__
      [155, 158], // run() has unnecessary None check
      [160, 165], // close() doesn't null out session/agent
    ],
  },
)
