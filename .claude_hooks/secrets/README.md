# Claude Hooks Secrets

This directory contains age-encrypted secrets that are decrypted during Claude Code session startup.

## Structure

Each `*.age` file decrypts to one of two JSON formats:

### Flat env vars (legacy, all other secrets)

```json
{ "ENV_VAR_NAME": "value", "ANOTHER_VAR": "another value" }
```

All keys are exported as shell environment variables.

### Typed secrets (new format)

```json
{"type": "<type>", ...fields}
```

The `"type"` discriminator triggers type-specific handling. Typed secrets are **not** exported
to the shell — they are consumed internally by the hook.

#### `kubeconfig`

```json
{
  "type": "kubeconfig",
  "server": "https://api.allegedly.works:16443",
  "token": "<ServiceAccount token>"
}
```

The API endpoint uses a publicly-trusted TLS certificate (via kube-api-proxy), so no
cluster CA is needed. If behind a TLS-inspecting proxy, the hook injects the proxy CA
into the kubeconfig so kubectl trusts the proxy's certificate.

## Kubeconfig Setup

The kubeconfig secret is regenerated automatically by `bazel run //cluster:bootstrap` after
cluster deployment. The bootstrap script uses `KubeconfigSecret` from
<tools/claude_hooks/kubeconfig_setup.py> to build and encrypt the secret.

## Security

- Secrets are encrypted with age (X25519)
- Decryption key is provided via `DUCKTAPE_CLAUDE_HOOKS_SECRETS_AGE_KEY` env var
- The `claude-code-web` ServiceAccount has access to the `claude-sandbox` namespace
- Resource quotas limit what can be created in the sandbox
