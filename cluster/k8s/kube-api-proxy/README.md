# kube-api-proxy

TLS passthrough route that exposes the in-cluster Kubernetes API on
`https://api.allegedly.works` (port 443) via the Cilium Gateway API.

## Why

Claude Code web sandboxes reach the internet through Anthropic's
TLS-inspecting egress proxy, which only permits port 443 outbound.
The k8s API must be reachable on `:443` for kubeconfig and cluster
access.

TLS passthrough (rather than termination) is needed so client
certificate authentication works end-to-end — the API server sees
the client cert directly and maps `O=` fields to Kubernetes groups.

## Topology

```text
Internet
   │ raw TLS (SNI: api.allegedly.works)
   ▼
Cilium Gateway (:443, TLS passthrough listener)
   │ raw TLS stream forwarded unchanged
   ▼
kubernetes.default.svc.cluster.local:443 (apiserver)
```

The API server cert has `api.allegedly.works` in its SANs (configured
via Talos `certSANs`). Clients must trust the cluster CA (`secrets/k8s-ca.crt`),
not the `*.allegedly.works` wildcard cert.

## Resources

| File                      | Purpose                                          |
| ------------------------- | ------------------------------------------------ |
| `tlsroute.yaml`           | TLSRoute to `kubernetes:443` (default namespace) |
| `kustomization.yaml`      | Flux kustomization root                          |
| `flux-kustomization.yaml` | Flux Kustomization (no `dependsOn`)              |
