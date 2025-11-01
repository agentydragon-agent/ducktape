# Ember Integration Tests

Run the object-store integration test against a real Kubernetes cluster:

```bash
cd helm_integration_tests
uv sync
uv run pytest
```

Ensure `helm` and `kubectl` point at a disposable cluster before running.

## CI Integration

The repository ships a Gitea Actions workflow (`.gitea/workflows/ci.yml`) that:

1. Spins up a temporary k3d cluster and runs these integration tests.
2. Builds and pushes the Ember image to `registry.k3s.agentydragon.com`.

To enable pushes, create an htpasswd robot account with the registry chart (see
`k8s/helm/registry/values.yaml`) and supply the plaintext credentials as Gitea
secrets:

- `REGISTRY_USER`
- `REGISTRY_PASSWORD`

CI logs into the registry via internal ingress and tags images with the commit
SHA (and `latest` on `main`).
