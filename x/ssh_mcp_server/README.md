# Agentplane SSH MCP server

This is the modular SSH backend for Agentplane's Action Service and Haku Console. It exposes two code-owned MCP
Actions:

- `list_targets` — list every configured `(host, user)` tuple and whether its mounted identity is
  currently available;
- `exec` — run one non-interactive command over SSH with an optional timeout bounded by the
  server's configured maximum.

The server owns transport and key selection only. It does not implement a command allowlist or
approval policy; each consumer authorizes the complete call before invoking this backend.

## Configuration

`SSH_MCP_CONFIG_FILE` points to YAML shaped like:

```yaml
known_hosts_file: /etc/agentplane-ssh/known_hosts
command_timeout_seconds: 300
connect_timeout_seconds: 10
output_limit_bytes: 65536
max_concurrent_executions: 4
targets:
  - host: wyrm2
    user: coder
    identity_file: /etc/agentplane-ssh/keys/wyrm2-coder
  - host: rugged
    user: coder
    identity_file: /etc/agentplane-ssh/keys/rugged-coder
```

Private keys are mounted files, not configuration values. Missing individual key files leave their
targets in `list_targets` with `available: false`; they do not remove the target or take down the
server. Duplicate `(host, user)` tuples are rejected as invalid configuration.

The HTTP MCP endpoint requires `Authorization: Bearer <SSH_MCP_BEARER_TOKEN>`. The standalone
[deployment](../../cluster/k8s/agentplane-ssh-mcp/README.md) uses one ESO-generated bearer
shared only with Haku Console and the staging Action Service. The endpoint is cluster-internal and has no public route.

Paramiko provides the SSH transport with strict reviewed `known_hosts`, disabled agent/key
search, disabled PTY, and bounded connect/command/output behavior. The remote command is passed
as a single SSH exec request; the server does not run a local shell.
