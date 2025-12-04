local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The code uses `MCPConfig(servers={})` but the correct parameter name is `mcpServers`,
    not `servers`. This creates an extra unwanted field in the config object.

    **Problem:**
    ```python
    # Current (WRONG):
    MCPConfig(servers={})
    # Result: {'mcpServers': {}, 'servers': {}}  # TWO fields!

    # Correct:
    MCPConfig()
    # Result: {'mcpServers': {}}  # ONE field, the right one

    # Or if being explicit:
    MCPConfig(mcpServers={})
    # Result: {'mcpServers': {}}
    ```

    **Verification:**
    ```python
    from fastmcp.mcp_config import MCPConfig
    default = MCPConfig()
    wrong = MCPConfig(servers={})
    print(default.model_dump())  # {'mcpServers': {}}
    print(wrong.model_dump())    # {'mcpServers': {}, 'servers': {}}
    print(default == wrong)      # False
    ```

    The `servers` parameter is accepted due to Pydantic's field aliasing or extra fields
    config, but it's not the canonical field name. This creates an extra field that
    shouldn't be there.

    **Current implementation (app.py:189):**
    ```python
    app.state.mcp_registry = InfrastructureRegistry(
        persistence=app.state.persistence,
        docker_client=app.state.docker_client,
        mcp_config=MCPConfig(servers={}),  # WRONG parameter name
        initial_policy=None,
    )
    ```

    **Correct approach:**
    Since the default is an empty dict anyway, just use:
    ```python
    mcp_config=MCPConfig(),
    ```

    Or if you want to be explicit about the empty servers:
    ```python
    mcp_config=MCPConfig(mcpServers={}),
    ```

    **Benefits:**
    1. Uses correct parameter name
    2. No extra unwanted field in the object
    3. Matches the actual MCPConfig schema
    4. Shorter (if using default)
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [189, 189],  // MCPConfig(servers={}) - wrong parameter
    ],
  },
)
