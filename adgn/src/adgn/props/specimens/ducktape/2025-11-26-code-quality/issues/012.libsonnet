local I = import '../../specimens/lib.libsonnet';

// iss-012: docker_client should be local variable, not app.state global

I.issueOneOccurrence(
  rationale= |||
    The `docker_client` is stored in `app.state` but is only used locally within the same
    function where it's created. It doesn't need to be global state - it should be a local
    variable that's dependency-injected into the components that need it.

    **Current implementation (app.py:155, 160, 188):**
    ```python
    app.state.docker_client = docker.from_env()
    app.state.registry = AgentRegistry(
        persistence=app.state.persistence,
        model=DEFAULT_MODEL,
        client_factory=default_client_factory,
        docker_client=app.state.docker_client,  # Line 160
    )
    # ... later in the same function ...
    app.state.mcp_registry = InfrastructureRegistry(
        persistence=app.state.persistence,
        docker_client=app.state.docker_client,  # Line 188
        mcp_config=MCPConfig(servers={}),
        initial_policy=None,
    )
    ```

    **Analysis:**
    - `docker_client` is set once on line 155
    - It's accessed ONLY on lines 160 and 188
    - Both accesses are in the SAME function where it's created
    - It's NEVER accessed from any other part of the codebase
    - The client is only used to pass to constructors during initialization

    **Problem:**
    - Putting it in `app.state` makes it global mutable state
    - This increases the "bag of random global state items" unnecessarily
    - It suggests the client might be used elsewhere (misleading)
    - Harder to track where the client is actually used

    **Correct approach:**
    Make it a local variable and pass it directly:

    ```python
    docker_client = docker.from_env()
    app.state.registry = AgentRegistry(
        persistence=app.state.persistence,
        model=DEFAULT_MODEL,
        client_factory=default_client_factory,
        docker_client=docker_client,
    )
    # ... later ...
    app.state.mcp_registry = InfrastructureRegistry(
        persistence=app.state.persistence,
        docker_client=docker_client,
        mcp_config=MCPConfig(servers={}),
        initial_policy=None,
    )
    ```

    **Benefits:**
    1. Less global state - cleaner architecture
    2. Clear scope - only exists where needed
    3. Self-documenting - usage is explicit and local
    4. Easier to test - no global state to mock
    5. Follows dependency injection pattern

    **Note:** Only put things in `app.state` if they need to be accessed from request
    handlers or other parts of the application. Local initialization dependencies should
    be local variables.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [155, 155],  // app.state.docker_client = (set)
      [160, 160],  // docker_client=app.state.docker_client (use 1)
      [188, 188],  // docker_client=app.state.docker_client (use 2)
    ],
  },
)
