local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `CompositorAdminClient` in compositor/clients.py (lines 17-48) does not follow the standard typed MCP server stub pattern used throughout the codebase.

    **Current problems:**
    1. Lines 17-23 define private `_AttachServerArgs` and `_DetachServerArgs` models that duplicate the public models already defined in compositor/admin.py (lines 10-18: `AttachServerArgs`, `DetachServerArgs`)
    2. Lines 26-48 manually construct tool calls using `build_mcp_function` and `call_simple_ok`, which is low-level and error-prone
    3. The client doesn't benefit from the typed stub infrastructure's automatic validation and error handling

    **The codebase has a standard pattern for typed MCP clients:**
    - Define a stub class that extends `ServerStub` (from `adgn.mcp.stubs.server_stubs`)
    - Declare methods with proper input/output types and `raise NotImplementedError`
    - The framework auto-wires the methods to actual tool calls at runtime

    **Example from approval_policy/clients.py (lines 14-28):**
    ```python
    class PolicyReaderStub(ServerStub):
        async def evaluate_policy(self, input: PolicyRequest) -> PolicyResponse:
            raise NotImplementedError  # Auto-wired at runtime
    ```

    **What should be done:**
    The CompositorAdminClient should be replaced with a typed stub that:
    1. Extends `ServerStub`
    2. Imports and reuses the public `AttachServerArgs` and `DetachServerArgs` from compositor/admin.py (no duplication)
    3. Declares typed methods like `async def attach_server(self, input: AttachServerArgs) -> SimpleOk: raise NotImplementedError`
    4. Relies on the framework's auto-wiring instead of manual tool name construction and calling

    This would eliminate code duplication, improve type safety, and follow established codebase conventions.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/compositor/clients.py': [
      [17, 23],  // Duplicated private arg models
      [26, 48],  // Manual CompositorAdminClient implementation
    ],
  },
)
