# MCP0 staging fixture

**P0 behavior:** a no-auth streamable-HTTP MCP origin exposing exactly one safe,
read-only, zero-argument tool, `fixture_info`, returning the text
`agentplane-mcp0-ok`. No clock, randomness, external I/O, credentials, resources,
prompts, or retained MCP sessions. This is an acceptance fixture, not a general MCP service.

Endpoint: `http://agentplane-mcp-fixture.agentplane-staging.svc.cluster.local:8080/mcp`.
`GET /healthz` returns `ok` for Kubernetes probes.

**Needed support:** `//x/agentplane/mcp_fixture:image` uses the existing FastMCP SDK
and OCI Python image convention. The CI image roster publishes to Forgejo; Flux's
shared image automation updates the staging Deployment. The initial image tag is
an intentionally nonexistent bootstrap sentinel: the Deployment cannot become
ready until the first merged `devel` image is published and Flux updates the tag.
No operator-created image or workload credential is required; the namespace already
receives the shared GitOps-owned registry pull secret.

The one non-root replica has a read-only root filesystem, no mounted service-account
token, 250m CPU/256Mi memory limits, and at most 16 concurrent HTTP connections/tasks.
Its Cilium policy denies all outbound connections and admits port 8080 only from
staging `agentplane-app` and `agentplane-actions` pods. The companion caller policy
adds only that destination to their existing egress permissions. No runner fence
is widened and there is no public HTTPRoute.

**Acceptance test:** `bbr test //x/agentplane/mcp_fixture:test_server` serves the same
stateless HTTP app on a real socket, connects without auth, discovers exactly the
annotated tool, and checks identical text over repeated calls and fresh connections.
Image build: `bbr build //x/agentplane/mcp_fixture:image`.
CI also validates the cluster manifests. These tests do not prove a live staging
rollout or a call from the Action Service.

**Deferred:** OAuth, MCP profiles, credential/binding design, Action Service
executor wiring, and live caller acceptance. This slice only supplies the origin
and narrow network reachability for that later integration.
