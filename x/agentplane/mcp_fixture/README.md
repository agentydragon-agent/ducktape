# MCP0 staging fixture

**P0 behavior:** a no-auth, stateless streamable-HTTP MCP origin exposing only
`fixture_info()` → `agentplane-mcp0-ok`, annotated read-only and idempotent. No tool
I/O, clock, randomness, credentials, resources, or prompts. The repo-pinned FastMCP
SDK implements MCP; this module only registers the constant tool and HTTP health route.
[Why not an external Everything image?](../../../debug/mcp_fixture_choice.md)

Endpoint: `http://agentplane-mcp-fixture.agentplane-staging.svc.cluster.local:8080/mcp`.
`GET /healthz` returns `ok` for Kubernetes probes.

**Needed support:** `//x/agentplane/mcp_fixture:image` follows the existing non-root
Python OCI convention. CI publishes to Forgejo; shared Flux image automation updates
the Deployment. The nonexistent bootstrap tag requires the first merged `devel`
publication and automated tag update before readiness. The namespace's existing
GitOps-owned registry pull secret is reused; no new credentials are needed.

The single replica has no service-account token, at most 16 concurrent HTTP
connections/tasks, and limits of 250m CPU, 256Mi memory, and 128Mi ephemeral storage.
The root filesystem remains writable for the existing image launcher's startup venv.
Cilium denies all fixture outbound connections and admits port 8080 only from staging
`agentplane-app` and `agentplane-actions`; companion caller egress permits only that
destination. No public route or runner-policy expansion.

**Acceptance:** `bbr test //x/agentplane/mcp_fixture:test_server` serves the production
ASGI app on a real socket, checks health, discovery, annotations, and identical results
over repeated calls and fresh no-auth connections. Build with
`bbr build //x/agentplane/mcp_fixture:image`; CI also validates cluster manifests.

**Deferred:** live staging rollout and real-Agent acceptance. Runtime executor/provider composition
is covered by `//x/agentplane/action_service:test_runtime`, not a live run. Deferred:
OAuth, profiles, and credential/binding design. The test does not prove those seams.
