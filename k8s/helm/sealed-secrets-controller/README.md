# sealed-secrets-controller Helm Chart

Packages the Bitnami sealed-secrets controller deployment plus CRDs and RBAC needed for the cluster.

## Usage

```bash
cd k8s/helm/sealed-secrets-controller
helm dependency build
helm upgrade --install sealed-secrets-controller . --namespace kube-system
```

Defaults match the legacy manifest (controller in `kube-system`, v0.24.5 image, CRD installed). Override image tags, resources, or namespace by supplying a values file:

```yaml
controller:
  image:
    tag: v0.26.0
  replicas: 2
crd:
  create: false  # if CRD managed elsewhere
```

The chart expects cert-manager CRDs and controllers to be present before installing.
