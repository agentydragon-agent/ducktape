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
