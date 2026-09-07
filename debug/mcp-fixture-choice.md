# Staging MCP fixture choice

## Decision

Keep the tiny fixture backed by the repository's locked FastMCP SDK rather than
adopt an external MCP server image. The acceptance boundary is one constant,
zero-argument, no-I/O tool over stateless HTTP, not broad MCP feature conformance.

## Observed evidence

Reviewed the official `modelcontextprotocol/servers` Everything implementation at
[`d73f99efbfd40c3aa1b61e88728b3d49fb52608f`](https://github.com/modelcontextprotocol/servers/tree/d73f99efbfd40c3aa1b61e88728b3d49fb52608f/src/everything):

- [README](https://github.com/modelcontextprotocol/servers/blob/d73f99efbfd40c3aa1b61e88728b3d49fb52608f/src/everything/README.md)
  advertises `mcp/everything` (without a digest) and supports streamable HTTP.
- [Features](https://github.com/modelcontextprotocol/servers/blob/d73f99efbfd40c3aa1b61e88728b3d49fb52608f/src/everything/docs/features.md)
  include environment disclosure (`get-env`), URL fetching and session resource
  registration (`gzip-file-as-resource`), mutable session logging/subscriptions,
  sampling, elicitation, and asynchronous tasks. Its benign echo/sum tools do not
  restrict the rest of the advertised surface.
- [Dockerfile](https://github.com/modelcontextprotocol/servers/blob/d73f99efbfd40c3aa1b61e88728b3d49fb52608f/src/everything/Dockerfile)
  uses tag-based Node bases, builder `npm install`, and a default command without
  the HTTP transport argument. The documented image's digest/provenance was not
  verified: the capability mismatch already disqualifies this candidate.

A verified digest could make an external image GitOps-compatible and immutable,
but would not make Everything deterministic, read-only, or limited to one tool.
Network egress denial does not prevent environment disclosure or client-side
sampling. Filtering/wrapping/forking it would introduce more ownership than the
existing constant-tool registration. This is not a claim that Everything is an
untrustworthy project; it is designed for a different test boundary.

## Smaller implementation

The retained fixture uses existing hash-locked Python dependencies, pinned OCI
base, CI publication, and shared Flux image automation, with no new external
runtime dependency. Removed the unnecessary server factory and async lifecycle
wrapper: one ASGI app is shared by production and the real-socket test, and
Uvicorn owns its lifecycle. Removed the unused local image-load target. Kept
HTTP health, connection limits, sandbox settings, and network manifests unchanged.
No hand-written JSON-RPC/MCP implementation or provider configuration is added.
