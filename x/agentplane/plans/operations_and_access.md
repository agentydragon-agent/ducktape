# Operations and access: remaining adapter work

The canonical Action lifecycle, catalog, Decisions, caller/operator projections, cancellation, and
notification-driven waits are implemented. Their contracts live in the
[Action Service specification](../action_service/SPEC.md) and [README](../action_service/README.md).
Claims, leases, unknown outcomes, and reconciliation live in
[executor liveness](../docs/executor_liveness.md); browser/operator authority lives in
[operator federation](../docs/operator_federation.md). Do not reopen these as first-adapter design gates.

The [task DAG](task_dag.md) tracks the remaining work. The existing credentialless MCP runtime and
review UI need deployed acceptance (`MCPDEPLOY` / `APPROVALUI`), not reimplementation; use the
[acceptance instructions](../acceptance/README.md).

## Credentialed upstream accounts (`MCPAUTH` / `CRED`)

Choose the account/credential owner and binding lifecycle before implementing a credentialed adapter.
A broker or existing account authority should own browser OAuth state, token exchange/refresh, and
durable account association; the harness must not receive those credentials. Action execution uses
a reviewed opaque account binding. Keep this outbound account connection separate from inbound
Claude.ai/Claude Code enrollment in [external MCP connections](external_mcp_connections.md).

Prove account linkage, discovery refresh, one safe read, refresh/reconnect, revocation, and isolation
from unbound/different accounts. If standalone operation requires new OAuth support, reuse existing
protocol machinery and implement only the separately tested missing seam. The credential owner and
static binding model require operator design confirmation; they do not gate the credentialless path.

## SSH execution adapter (`SSHEXEC`)

A concrete long-running consumer must define the backend's supported, authenticated and bounded
progress/status/output-so-far observations for the existing Execution. Use authoritative
reconciliation only where the backend supports it; otherwise retain an unknown outcome. A missed
heartbeat cannot prove an external effect stopped. Status reads never create another dispatch or
blind retry.

The planned SSH adapter uses OpenSSH as the transport, Kubernetes Secrets for private keys, and a
reviewed ConfigMap for machine/user/key bindings. The binding controls which credential may reach
which remote account; it is not a command policy. The existing decider/Decision layer authorizes the
complete Action, including the command and target, and the SSH layer must not introduce a second
command allowlist. The executor implementation owns the `list_targets` and `exec` Action names and
schemas; configuration supplies only the target/key/transport data those Actions consume.

The Action Service must never receive reusable private-key material. Prefer mounted files for the
initial implementation; evaluate an isolated SSH-agent sidecar only against a concrete rotation or
key-isolation need. Preserve strict host-key verification, bounded output, exactly-one dispatch, and
safe terminal/unknown results. See [the SSH executor plan](ssh_executor.md).

Prove exactly one invocation, authorized/redacted observations, safe terminal or unknown results,
and duplicate-start refusal against the concrete backend. Do not build a generic worker transport
without a consumer requiring it. Broader delegated-versus-brokered policy is in
[external access](external_access.md); standing grants remain separate access objects.

## Delivery and policy

[Asynchronous approvals](async_approvals.md) owns remaining human notification and Thread delivery.
[Action policies](action_policies.md) owns future mandatory bounds and reusable auto-approval policy
bindings. Neither adds another Action lifecycle, event store, or approval authority.
