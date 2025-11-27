local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    The notification wiring code (lines 833-932) contains 4 notifier factory functions that follow the exact same pattern with duplicated boilerplate. This common structure should be extracted into a helper function.

    **Duplicated pattern in 4 notifiers:**

    1. `make_policy_notifier` (lines 841-855)
    2. `make_ui_state_notifier` (lines 884-898)
    3. `make_session_state_notifier` (lines 901-915)
    4. `make_approval_hub_notifier` (lines 858-878) - same pattern but broadcasts multiple URIs

    **Common structure repeated in each:**

    All four follow this pattern:
    - Notifier is sync, schedule broadcast in event loop
    - `loop.create_task(server.broadcast_resource_updated(uri))`
    - `add_done_callback` with lambda for success/failure logging
    - Fire and forget (don't await task)

    **Example of one instance (make_policy_notifier, lines 841-855):**

    ```python
    def make_policy_notifier(aid: str):
        def notifier(uri: str):
            loop = asyncio.get_running_loop()
            _task = loop.create_task(server.broadcast_resource_updated(uri))
            _task.add_done_callback(
                lambda t: logger.debug(f"Broadcast complete for {uri}")
                if not t.exception()
                else logger.warning(f"Broadcast failed for {uri}: {t.exception()}")
            )
        return notifier
    ```

    **Comparison of the 4 notifiers:**

    | Notifier | Lines | URI Source | Takes Param | Multiple URIs |
    |----------|-------|------------|-------------|---------------|
    | make_policy_notifier | 841-855 | Parameter `uri` | Yes | No |
    | make_ui_state_notifier | 884-898 | `resources.agent_ui_state(aid)` | No | No |
    | make_session_state_notifier | 901-915 | `resources.agent_session_state(aid)` | No | No |
    | make_approval_hub_notifier | 858-878 | 3 approval resources | No | Yes |

    All use identical `loop.create_task` + `add_done_callback` boilerplate, just with different URIs and log context.

    **Why this is problematic:**

    1. Massive duplication: The same 10-15 line pattern repeated 4 times
    2. Hard to maintain: Changes to broadcast pattern must update 4 identical copies
    3. Error-prone: Easy to update one notifier but forget the others
    4. Verbose: ~60 lines of code for what should be ~15 lines + 4 simple calls

    **Recommended fix:**

    Create a helper function that handles the common pattern:

    ```python
    def make_sync_broadcast_notifier(
        *,
        uri_getter: Callable[[], str | list[str]],
        log_context: str
    ) -> Callable[[], None]:
        """Create a sync notifier that broadcasts resource updates.

        Args:
            uri_getter: Function that returns URI or list of URIs to broadcast
            log_context: Context string for log messages (e.g., "policy", "UI state")

        Returns:
            Sync notifier function that schedules broadcasts as fire-and-forget tasks
        """
        def notifier():
            loop = asyncio.get_running_loop()
            uris = uri_getter()
            if isinstance(uris, str):
                uris = [uris]

            for uri in uris:
                _task = loop.create_task(server.broadcast_resource_updated(uri))
                _task.add_done_callback(
                    lambda t, u=uri: logger.debug(f"{log_context} broadcast complete for {u}")
                    if not t.exception()
                    else logger.warning(f"{log_context} broadcast failed for {u}: {t.exception()}")
                )

        return notifier
    ```

    **Benefits:**
    - Single source of truth (~15 lines instead of ~60)
    - Changes to broadcast logic happen in one place
    - More concise usage code
    - Harder to make mistakes
    - Clearer intent (helper name documents the pattern)

    **Note:**

    `make_mount_listener` (lines 918-926) is different - it's async and awaits the broadcast, so it shouldn't be included in this refactoring. The registry_notifier (lines 929-930) is also different (already async and simple).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [841, 855],
      [858, 878],
      [884, 898],
      [901, 915],
    ],
  },
)
