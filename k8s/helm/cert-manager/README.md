# cert-manager Helm Chart

Installs the self-signed bootstrap issuer, homelab CA certificate, and CA ClusterIssuer used across the cluster.

## Usage

```bash
cd k8s/helm/cert-manager
helm dependency build
helm upgrade --install cert-manager . --namespace cert-manager
```

Values let you customize the CA metadata:

```yaml
caCertificate:
  commonName: "My Lab CA"
  secretName: lab-ca-secret
  organizations:
    - mylab
caClusterIssuer:
  name: lab-ca-issuer
  secretName: lab-ca-secret
```

## Notes

- The chart assumes cert-manager CRDs and controllers are already installed.
- It does not manage the `cert-manager` namespace; ensure it exists before installing or set `--namespace cert-manager --create-namespace` on the upgrade command.
