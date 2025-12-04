local I = import '../../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-22-00',
  rationale= |||
    Two functions declare parameters that are never used in the function body. These are vestigial parameters from previous implementations.

    **Problem 1: attach_default_servers() unused parameters**

    The function declares `agent_id`, `persistence`, and `docker_client` parameters but never uses them (auto_attach.py, lines 40-42). Only `comp`, `ui_bus`, and `approval_engine` are actually used.

    Remove unused parameters:
    ```python
    async def attach_default_servers(
        comp: Compositor, *, ui_bus, approval_engine
    ) -> None:
    ```

    **Problem 2: build_handlers() unused parameters**

    The function declares `approval_engine`, `approval_hub`, and `agent_id` parameters but never uses them (handlers.py, lines 19-31). Only `poll_notifications`, `manager`, `persistence`, `get_run_id`, and `ui_bus` are actually used.

    Remove unused parameters:
    ```python
    def build_handlers(
        *,
        poll_notifications: Callable[[], NotificationsBatch],
        manager: ConnectionManager,
        persistence: Persistence,
        get_run_id: Callable[[], UUID | None],
        ui_bus: ServerBus | None = None,
    ) -> tuple[list[BaseHandler], RunPersistenceHandler]:
    ```

    **How this happened:**

    Likely scenario:
    1. Earlier version needed these parameters to pass to helper functions
    2. Helper functions were refactored to get data elsewhere (e.g., from `comp`)
    3. Parameters were removed from helpers but not from the top-level function
    4. No warnings because Python allows unused parameters

    **Prevention:**

    - Use linter that detects unused parameters (Ruff rule ARG001/ARG002)
    - Review function signatures when refactoring call sites
    - Add `# noqa: ARG001` if intentionally unused (e.g., protocol implementation)
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/auto_attach.py': [[40, 42]],
    'adgn/src/adgn/agent/runtime/handlers.py': [[19, 31]],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/runtime/auto_attach.py'],
    ['adgn/src/adgn/agent/runtime/handlers.py'],
  ],
)
