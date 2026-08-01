# Haku Agent SDK authentication spike

This directory owns the temporary workload used to answer the
blocking authentication question in
[`haku/plans/agent_sdk_sandbox_runtime.md`](../../../../haku/plans/agent_sdk_sandbox_runtime.md):
whether the Claude Agent SDK accepts a long-lived Claude Code subscription OAuth
token in a headless, TLS-intercepted Kubernetes workload.

The workload receives only `sk-ant-oat01-proxy-haku-claude-placeholder`. The real
`CLAUDE_CODE_OAUTH_TOKEN` is encrypted under
`cluster/k8s/agents/haku-egress-proxy/` and exists at runtime only in the dedicated
`haku-claude-oauth-proxy` pod. That proxy substitutes the placeholder only in an
`Authorization` header sent to exactly `api.anthropic.com`. Do not paste the token
into a PR comment, shell trace, Job manifest, sandbox, or log.

## Verification Job

The one-shot `haku-agent-sdk-smoke` Job exercises the assumptions needed by the
larger runtime before any console or Sandbox CR plumbing is built:

- subscription OAuth authentication from a headless container;
- partial-message streaming and explicit fine-grained tool-input streaming configuration;
- two turns on one `ClaudeSDKClient`;
- closing the client and resuming its disk-backed session at the same `cwd`;
- `UserPromptSubmit`, `Stop`, and deny-all `PreToolUse` hooks;
- the namespace's forced egress path, dedicated OAuth substitution, and injected CA bundle; and
- Claude Code OTel configuration passed through `ClaudeAgentOptions.env`.

The Job has no Kubernetes service-account token and exposes no tools to Claude.
It deliberately remains after completion so its status and logs are inspectable:

```console
kubectl -n haku-sandbox logs job/haku-agent-sdk-smoke
kubectl -n haku-sandbox get job haku-agent-sdk-smoke
```

Changing the image tag causes Flux to replace and rerun the Job because the Job
has the `kustomize.toolkit.fluxcd.io/force` annotation.

## Result

The live probe passed on 2026-07-31 with Agent SDK 0.1.48 and Claude CLI 2.1.71.
The Job completed in 11 seconds with exit code 0 and no restart. It established
that:

- `CLAUDE_CODE_OAUTH_TOKEN` authenticates the SDK headlessly against the
  operator's Claude subscription;
- the CLI can reach Anthropic through Haku's forced proxy and intercepted TLS;
- partial-message streaming, same-client state, and close/reopen resume at a
  fixed `cwd` work;
- Claude Code creates a populated JSONL transcript in `CLAUDE_CONFIG_DIR`;
- `UserPromptSubmit` and `Stop` Python hooks fire for each turn; and
- the no-tools probe made no tool attempt and retained one session ID across all
  three turns.

See
[`haku/plans/agent_sdk_sandbox_runtime.md`](../../../../haku/plans/agent_sdk_sandbox_runtime.md)
for the detailed evidence, remaining experiments, and decision to proceed with
the runtime build. In particular, telemetry configuration was passed to the CLI
but actual OTel arrival still needs to be confirmed in the backend.
