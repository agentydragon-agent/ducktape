# Vendored Browsertrix chart

This chart is based on Webrecorder Browsertrix `v1.24.2`:

- Repository: <https://github.com/webrecorder/browsertrix>
- Upstream commit: `380ed775c9d5b759624ec4b04711e42e3450d413`
- License: AGPL-3.0; see `LICENSE.browsertrix`

Ducktape carries a narrow downstream patch because the upstream chart:

- grants its Kubernetes controller permissions to both the namespace's
  `default` ServiceAccount and `system:anonymous`;
- has no way to assign those permissions to a dedicated ServiceAccount;
- couples the application's public origin to creation of an Ingress; and
- only enables the frontend's same-origin object-storage proxy for bundled
  MinIO.

The downstream patch removes anonymous access, gives the backend and generated
background jobs a dedicated controller ServiceAccount, prevents unrelated
workloads from mounting that token, supports arbitrary node selectors and a
Gateway API deployment through `external_url`, and permits proxying the existing
in-cluster SeaweedFS S3 bucket without deploying MinIO. Mutable crawler and
rclone image tags are pinned for reproducible deployments.
