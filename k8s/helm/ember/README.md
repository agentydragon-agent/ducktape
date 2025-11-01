# Ember Agent Chart

Helm chart that deploys an Ember agent pod plus supporting config and secret
projections.

## Install

```bash
cd k3s/helm/ember
helm dependency update
helm upgrade --install ember-dev . \
  --namespace ember-dev --create-namespace \
  --values values.yaml \
  --set config.matrix.base_url=https://matrix.example.com \
  --set runtimeSecrets.matrixTokenSecret=matrix-ember-token-dev
```

## Object store overrides

When pairing with the `minio-ember` chart, override the `objectStore` block per
release:

```yaml
objectStore:
  enabled: true
  endpoint: https://objectstore.example.com
  bucket: ember-dev-media
  secretName: ember-dev-objectstore
  secure: true
  urlExpirySeconds: 180
  accessKeyKey: access-key
  secretKeyKey: secret-key
```

The runtime reads the projected keys for every upload, so rotation via
reflector-based secrets works without a restart.

Consult `values.schema.json` for the full list of supported overrides.
