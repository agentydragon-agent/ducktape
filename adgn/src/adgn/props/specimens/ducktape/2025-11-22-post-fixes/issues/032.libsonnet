local I = import '../../specimens/lib.libsonnet';

// iss-032: Misleading comment and dead parameters

I.issueOneOccurrence(
  rationale= |||
    Three related issues with dead parameters and misleading documentation:

    **Problem 1: Misleading comment about dependencies**

    The shim.py module docstring says "Keep this tiny and dependency-free; only
    stdlib is used" but this is misleading. Policies actually do import and use
    types/enums from the `adgn` package, which is installed in the container image.

    **Current implementation (shim.py, lines 14-17):**
    ```python
    Notes:
    - Keep this tiny and dependency-free; only stdlib is used.
    - Container image must have the adgn package installed so `python -m
      adgn.agent.policy_eval.shim` resolves.
    ```

    **Why this is misleading:**

    The comment says "only stdlib is used" but immediately below it says the container
    needs the `adgn` package installed. Policy programs routinely import from `adgn`:

    ```python
    # Typical policy code
    from adgn.agent.policies.policy_types import PolicyDecision
    from adgn.mcp._shared.naming import build_mcp_function

    # Use adgn types and utilities
    return PolicyDecision.ALLOW
    ```

    **The correct approach:**

    Clarify what "dependency-free" means:

    ```python
    Notes:
    - The shim itself only uses stdlib (no third-party imports).
    - Policy programs CAN import from adgn package (installed in container).
    - Container image must have the adgn package installed so both the shim
      (python -m adgn.agent.policy_eval.shim) and policy programs can use it.
    ```

    Or simply remove the misleading statement:

    ```python
    Notes:
    - Container image must have the adgn package installed for both the shim
      execution (python -m adgn.agent.policy_eval.shim) and for policy programs
      to import types/utilities from adgn.
    ```

    **The confusion:**

    "Dependency-free" could mean:
    1. The shim.py module doesn't import non-stdlib (TRUE)
    2. Policy programs don't use adgn package (FALSE - they do!)
    3. No external packages needed in container (FALSE - adgn is needed)

    The current wording suggests interpretation #2, which is wrong.

    **Problem 2: Dead parameters in attach_default_servers()**

    The function declares `agent_id`, `persistence`, and `docker_client` parameters
    but never uses them. These are vestigial parameters from a previous implementation.

    **Current implementation (auto_attach.py, lines 40-58):**
    ```python
    async def attach_default_servers(
        comp: Compositor, *, agent_id: AgentID, persistence, docker_client, ui_bus, approval_engine
    ) -> None:
        """Attach the standard UI + approval policy + runtime exec servers.

        Inlines UI + policy wiring locally.
        """
        # UI server
        await attach_ui(comp, ui_bus)
        # Approval policy servers
        await attach_approval_policy_readonly(comp, approval_engine)
        # Do not mount admin (approver) server into the compositor; UI uses a private client.
        await attach_approval_policy_proposer(comp, approval_engine)
        # Runtime exec server (no host mounts)
        runtime_image = resolve_runtime_image()
        opts = ContainerOptions(image=runtime_image, volumes=None, ephemeral=True)
        await attach_runtime(comp, opts)
    ```

    Notice:
    - `agent_id` is not used
    - `persistence` is not used
    - `docker_client` is not used

    Only `comp`, `ui_bus`, and `approval_engine` are actually used.

    **The correct approach:**

    Remove unused parameters:

    ```python
    async def attach_default_servers(
        comp: Compositor, *, ui_bus, approval_engine
    ) -> None:
        """Attach the standard UI + approval policy + runtime exec servers.

        Inlines UI + policy wiring locally.
        """
        # UI server
        await attach_ui(comp, ui_bus)
        # Approval policy servers
        await attach_approval_policy_readonly(comp, approval_engine)
        await attach_approval_policy_proposer(comp, approval_engine)
        # Runtime exec server (no host mounts)
        runtime_image = resolve_runtime_image()
        opts = ContainerOptions(image=runtime_image, volumes=None, ephemeral=True)
        await attach_runtime(comp, opts)
    ```

    **How did this happen?**

    Likely scenario:
    1. Earlier version needed these parameters to pass to helper functions
    2. Helper functions were refactored to get data elsewhere (e.g., from `comp`)
    3. Parameters were removed from helpers but not from the top-level function
    4. No warnings because Python allows unused parameters

    **How to prevent:**

    - Use a linter that detects unused parameters (Ruff rule ARG001/ARG002)
    - Review function signatures when refactoring call sites
    - Use type checkers that warn about unused parameters
    - Add `# noqa: ARG001` if intentionally unused (e.g., protocol implementation)

    **Verification:**

    Check all callers to ensure they're not relying on these parameters:

    ```bash
    git grep -n 'attach_default_servers'
    # Update all call sites to remove the unused arguments
    ```

    **Problem 3: More dead parameters in build_handlers()**

    The `build_handlers()` function declares `approval_engine`, `approval_hub`, and
    `agent_id` parameters but never uses them.

    **Current implementation (handlers.py, lines 19-42):**
    ```python
    def build_handlers(
        *,
        poll_notifications: Callable[[], NotificationsBatch],
        manager: ConnectionManager,
        persistence: Persistence,
        approval_engine: ApprovalPolicyEngine,  # ← Not used
        approval_hub: ApprovalHub,              # ← Not used
        get_run_id: Callable[[], UUID | None],
        agent_id: AgentID,                      # ← Not used
        ui_bus: ServerBus | None = None,
    ) -> tuple[list[BaseHandler], RunPersistenceHandler]:
        """Construct the standard handler stack for an agent."""
        persist_handler = RunPersistenceHandler(persistence=persistence, get_run_id=get_run_id)
        handlers: list[BaseHandler] = [manager, persist_handler]
        if ui_bus is not None:
            handlers.extend([
                ServerModeHandler(bus=ui_bus, poll_notifications=poll_notifications),
                DisplayEventsHandler()
            ])
        else:
            handlers.append(NotificationsHandler(poll_notifications))
        return handlers, persist_handler
    ```

    Only `poll_notifications`, `manager`, `persistence`, `get_run_id`, and `ui_bus`
    are actually used.

    **The correct approach:**

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
        """Construct the standard handler stack for an agent."""
        persist_handler = RunPersistenceHandler(persistence=persistence, get_run_id=get_run_id)
        handlers: list[BaseHandler] = [manager, persist_handler]
        if ui_bus is not None:
            handlers.extend([
                ServerModeHandler(bus=ui_bus, poll_notifications=poll_notifications),
                DisplayEventsHandler()
            ])
        else:
            handlers.append(NotificationsHandler(poll_notifications))
        return handlers, persist_handler
    ```

    **Summary:**

    1. Clarify shim.py comment: "shim is stdlib-only, policies can use adgn"
    2. Remove unused `agent_id`, `persistence`, `docker_client` from `attach_default_servers()`
    3. Remove unused `approval_engine`, `approval_hub`, `agent_id` from `build_handlers()`
  |||,
  properties=['accurate-documentation', 'remove-dead-code'],
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/shim.py': [
      [14, 17],  // Misleading "dependency-free" comment
    ],
    'adgn/src/adgn/agent/runtime/auto_attach.py': [
      [40, 42],  // Dead parameters: agent_id, persistence, docker_client
    ],
    'adgn/src/adgn/agent/runtime/handlers.py': [
      [19, 31],  // Dead parameters: approval_engine, approval_hub, agent_id
    ],
  },
  gap_note= |||
    This finding illustrates **"accurate-documentation"**: comments and docstrings
    should precisely describe what the code does, not create confusion or state
    things that are misleading when read literally.

    Common documentation pitfalls:
    - Ambiguous terms ("dependency-free" - of what?)
    - Outdated comments from previous implementations
    - Comments that contradict immediately following statements
    - Using "should" when you mean "must" or "can"

    How to write clear documentation:
    - Be specific: "shim is stdlib-only" vs "only stdlib is used" (by whom?)
    - State what IS true, not what isn't: "policies CAN import adgn" vs "no dependencies"
    - Keep comments and code in sync during refactoring
    - Remove misleading statements rather than leaving them vague

    Related to **"remove-dead-code"**: unused function parameters are a form of
    dead code. They:
    - Confuse readers (why is this parameter here?)
    - Make call sites more verbose (passing unused args)
    - Hide refactoring opportunities (can't see true dependencies)
    - Create maintenance burden (must keep in sync across call sites)

    How to detect dead parameters:
    - Ruff rule ARG001 (unused function argument)
    - Ruff rule ARG002 (unused method argument)
    - Pylint unused-argument warning
    - IDE graying out unused variables

    When unused parameters ARE appropriate:
    - Implementing a protocol/interface that requires them
    - Placeholder for future implementation (document with TODO)
    - Callback signature that might not use all parameters
    - Testing/mocking where signature must match

    In these cases: add `# noqa: ARG001` or `_ = param` to show it's intentional.
  |||,
)
