# Observability Umbrella Chart

Installs the namespace (`base`), OpenAI probe, and TimescaleDB components together.

```bash
cd k8s/helm/observability
helm dependency build
helm upgrade --install observability . --namespace observability --create-namespace
```

Override subchart values under the corresponding keys, for example:

```yaml
openai-probe:
  sealedSecret:
    enabled: false
    name: my-openai-secret

timescaledb:
  persistence:
    size: 20Gi
```
