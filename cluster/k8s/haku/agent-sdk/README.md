# Haku Agent SDK authentication spike

This directory owns the credentials and temporary workload used to answer the
blocking authentication question in
[`haku/plans/agent_sdk_sandbox_runtime.md`](../../../../haku/plans/agent_sdk_sandbox_runtime.md):
whether the Claude Agent SDK accepts a long-lived Claude Code subscription OAuth
token in a headless, TLS-intercepted Kubernetes workload.

Before merging the credential scaffold, replace the placeholder with the output
of `claude setup-token` and encrypt it at its final path so the repository's SOPS
creation rule selects the cluster recipient:

```console
sops --encrypt --in-place cluster/k8s/haku/agent-sdk/claude-code-oauth-token.sops.yaml
```

The committed file must contain an `ENC[...]` value and a `sops:` metadata block.
Do not paste the token into a PR comment, shell trace, Job manifest, or log.

## Verification Job

The one-shot `haku-agent-sdk-smoke` Job exercises the assumptions needed by the
larger runtime before any console or Sandbox CR plumbing is built:

- subscription OAuth authentication from a headless container;
- partial-message streaming and terminal result metadata;
- two turns on one `ClaudeSDKClient`;
- closing the client and resuming its disk-backed session at the same `cwd`;
- `UserPromptSubmit`, `Stop`, and deny-all `PreToolUse` hooks;
- the namespace's forced egress proxy and injected CA bundle; and
- Claude Code OTel configuration passed through `ClaudeAgentOptions.env`.

The Job has no Kubernetes service-account token and exposes no tools to Claude.
It deliberately remains after completion so its status and logs are inspectable:

```console
kubectl -n haku-sandbox logs job/haku-agent-sdk-smoke
kubectl -n haku-sandbox get job haku-agent-sdk-smoke
```

Changing the image tag causes Flux to replace and rerun the Job because the Job
has the `kustomize.toolkit.fluxcd.io/force` annotation.
