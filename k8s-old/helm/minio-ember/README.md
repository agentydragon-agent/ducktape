# MinIO Ember Chart

Single-node MinIO deployment tailored for Ember agents. Each Helm release can create its own bucket + credential pair while sharing the same MinIO instance.

## Usage

```bash
cd k8s/helm/minio-ember
helm dependency update
helm upgrade --install minio-ember-production . \
  --namespace ember-objectstore --create-namespace \
  --set tenant.bucketName=ember-prod-media \
  --set tenant.accessSecretName=ember-prod-objectstore \
  --set tenant.secretNamespace=ember-prod
```

The bootstrap job will:

1. Create (or reuse) the bucket.
2. Create a service user matching `tenant.accessSecretName`.
3. Attach the generated policy granting scoped access to that bucket.

Secrets are annotated for [emberstack/kubernetes-reflector](https://github.com/emberstack/kubernetes-reflector) so the access secret automatically mirrors into `tenant.secretNamespace`, making it consumable by the Ember deployment.

## Values

The supplied `values.schema.json` documents every tunable field. Run `helm show values ./` or consult the schema to discover overrides (e.g. TLS ingress host, PVC size, resource requests).
