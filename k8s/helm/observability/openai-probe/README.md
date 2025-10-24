# observability-openai-probe Helm Chart

Deploys the OpenAI API probe used for observability metrics.

```bash
cd k8s/helm/observability/openai-probe
helm dependency build
helm upgrade --install observability-openai-probe . --namespace observability
```

Values control image tag, probe args, and secret references for the OpenAI API key and TimescaleDB password. Adjust `env.openaiSecretName` or `env.timescaledbSecretName` if you rename the SealedSecrets.

To ship pre-sealed credentials from git, leave `sealedSecret.enabled=true` and update `sealedSecret.encryptedData.api_key` with a freshly generated value from `kubeseal`.
