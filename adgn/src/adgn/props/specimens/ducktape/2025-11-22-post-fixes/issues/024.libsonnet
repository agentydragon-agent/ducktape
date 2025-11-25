local I = import '../../specimens/lib.libsonnet';

// iss-024: Duplicated agent info construction and thin wrapper methods

I.issueOneOccurrence(
  rationale= |||
    The code has two problems in server.py:

    **Problem 1: Duplicated agent info construction**

    Both `list_agents()` and `get_agent_info()` build the same `AgentInfo` object
    with identical logic (determine run phase, check mode, build capabilities), but
    the implementation is duplicated line-by-line instead of extracting a shared helper.

    **Current implementation (server.py, lines 252-300):**
    ```python
    @self.resource("resource://agents/list", ...)
    async def list_agents() -> AgentsListResponse:
        """List all agents with detailed status."""
        agents = []
        for agent_id, entry in self._agents.items():
            if entry.agent is None:
                continue

            agent = entry.agent
            infra = agent.running
            live = infra is not None
            run_phase, pending_approvals = self._determine_run_phase(infra)
            is_local = agent.mode == AgentMode.LOCAL

            agents.append(
                AgentInfo(
                    id=agent_id,
                    mode=agent.mode,
                    live=live,
                    run_phase=run_phase,
                    pending_approvals=pending_approvals,
                    capabilities=AgentCapabilities(chat=is_local, agent_loop=is_local),
                )
            )
        return AgentsListResponse(agents=agents)

    @self.resource("resource://agents/{agent_id}/info", ...)
    async def get_agent_info(agent_id: AgentID) -> AgentInfo:
        """Get detailed information about a specific agent."""
        agent = self._get_agent_or_raise(agent_id)

        infra = agent.running
        live = infra is not None
        run_phase, pending_approvals = self._determine_run_phase(infra)
        is_local = agent.mode == AgentMode.LOCAL

        return AgentInfo(
            id=agent_id,
            mode=agent.mode,
            live=live,
            run_phase=run_phase,
            pending_approvals=pending_approvals,
            capabilities=AgentCapabilities(chat=is_local, agent_loop=is_local),
        )
    ```

    **The correct approach:**

    Extract a helper method and reuse it:
    ```python
    def _build_agent_info(self, agent_id: AgentID, agent: Agent) -> AgentInfo:
        """Build AgentInfo from an agent instance."""
        infra = agent.running
        live = infra is not None
        run_phase, pending_approvals = self._determine_run_phase(infra)
        is_local = agent.mode == AgentMode.LOCAL

        return AgentInfo(
            id=agent_id,
            mode=agent.mode,
            live=live,
            run_phase=run_phase,
            pending_approvals=pending_approvals,
            capabilities=AgentCapabilities(chat=is_local, agent_loop=is_local),
        )

    @self.resource("resource://agents/list", ...)
    async def list_agents() -> AgentsListResponse:
        """List all agents with detailed status."""
        agents = [
            self._build_agent_info(agent_id, entry.agent)
            for agent_id, entry in self._agents.items()
            if entry.agent is not None
        ]
        return AgentsListResponse(agents=agents)

    @self.resource("resource://agents/{agent_id}/info", ...)
    async def get_agent_info(agent_id: AgentID) -> AgentInfo:
        """Get detailed information about a specific agent."""
        agent = self._get_agent_or_raise(agent_id)
        return self._build_agent_info(agent_id, agent)
    ```

    Or even simpler - `list_agents` could just call `get_agent_info`:
    ```python
    @self.resource("resource://agents/list", ...)
    async def list_agents() -> AgentsListResponse:
        """List all agents with detailed status."""
        agents = [
            await get_agent_info(agent_id)
            for agent_id, entry in self._agents.items()
            if entry.agent is not None
        ]
        return AgentsListResponse(agents=agents)
    ```

    **Problem 2: Thin wrapper methods**

    Methods `get_infrastructure()`, `get_agent_mode()`, and `get_local_runtime()`
    are trivial wrappers that just call `_get_agent_or_raise()` and access one field.

    **Current implementation (server.py, lines 187-198):**
    ```python
    async def get_infrastructure(self, agent_id: AgentID) -> RunningInfrastructure:
        """Get infrastructure. Raises KeyError if not found."""
        return self._get_agent_or_raise(agent_id).running

    def get_agent_mode(self, agent_id: AgentID) -> AgentMode:
        """Get agent mode. Raises KeyError if not found."""
        return self._get_agent_or_raise(agent_id).mode

    def get_local_runtime(self, agent_id: AgentID) -> LocalAgentRuntime | None:
        """Get local runtime or None if bridge agent. Raises KeyError if not found."""
        return self._get_agent_or_raise(agent_id).local_runtime
    ```

    **The correct approach:**

    Let callers use `_get_agent_or_raise()` directly:
    ```python
    # Instead of:
    infra = self.get_infrastructure(agent_id)

    # Do:
    agent = self._get_agent_or_raise(agent_id)
    infra = agent.running
    ```

    Or if `_get_agent_or_raise` should be public, rename it:
    ```python
    def get_agent(self, agent_id: AgentID) -> Agent:
        """Get agent. Raises KeyError if not found or not initialized."""
        entry = self._agents.get(agent_id)
        if entry is None:
            raise KeyError(f"Agent {agent_id} not found")
        if entry.agent is None:
            raise KeyError(f"Agent {agent_id} not yet initialized")
        return entry.agent

    # Then callers do:
    agent = self.get_agent(agent_id)
    infra = agent.running
    mode = agent.mode
    runtime = agent.local_runtime
    ```

    **Benefits:**

    1. **Less code duplication**: One implementation of agent info building
    2. **Easier to maintain**: Changes to AgentInfo construction happen in one place
    3. **Simpler API**: Fewer methods with clearer responsibilities
    4. **More direct**: Callers access agent fields directly instead of through wrappers
    5. **Better testability**: Can test `_build_agent_info` independently

    **Why thin wrappers are harmful:**

    - Add noise without meaningful abstraction
    - Make it harder to see what's actually being accessed
    - Increase maintenance burden (more methods to document, test, maintain)
    - Don't add meaningful encapsulation (just one field access)
    - Force readers to jump between methods to understand simple operations
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
