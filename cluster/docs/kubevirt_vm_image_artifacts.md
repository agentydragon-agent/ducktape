# KubeVirt VM Image Artifacts

KubeVirt bootstrap disks are published as S3 objects in SeaweedFS, then imported
into persistent VM root PVCs with CDI `DataVolume` resources.

## Public Endpoint

Use the dedicated endpoint:

```bash
https://vm-images-s3.allegedly.works
```

This route must point only at the `seaweedfs/vm-images-s3` Service. Do not route
it to the operator-managed `seaweedfs-s3` Service, which mounts the all-tenant S3
config.

The dedicated gateway mounts a separate S3 config with only:

- `vm-images-ci-writer`: read/write/list/tagging on bucket `vm-images`
- `vm-images-cdi-reader`: read/list on bucket `vm-images`

## Source Of Truth

Secrets come from SOPS and are applied by Flux:

```text
cluster/k8s/seaweedfs/vm-images-s3/credentials.sops.yaml
```

Do not manually create `vm-images-s3-credentials` during normal operation. Local
admin shells may not be able to decrypt this file because it is encrypted to the
cluster SOPS key; that is intentional. Commit and push the SOPS file, then let
Flux decrypt it.

GitHub Actions upload credentials are synced from the same Kubernetes Secret by
`tf/gitops/github-secrets-sync` into repository secrets:

- `VM_IMAGES_S3_ACCESS_KEY_ID`
- `VM_IMAGES_S3_SECRET_ACCESS_KEY`

## Publishing A Bootstrap Image

`.github/workflows/vm-images.yml` builds `.#bootstrap-image`, then uploads the
qcow2 output:

```bash
nix build .#bootstrap-image
aws --endpoint-url https://vm-images-s3.allegedly.works \
  s3 cp result/*.qcow2 "s3://vm-images/bootstrap/${GITHUB_SHA}.qcow2"
```

Use commit-addressed object keys. Existing VMs should not auto-replace their root
PVC when a new bootstrap image is published; the bootstrap image is for first
provisioning and recovery.

The first push that introduces this wiring may skip the workflow because the
GitHub repository secrets do not exist until Flux applies the SOPS Secret and
`github-secrets-sync` reconciles. After that, dispatch the workflow manually or
let the next matching push publish the image.

## Importing With CDI

Create a reader Secret in the VM namespace using the CDI key names:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gecko-vm-images-s3-reader
  namespace: gecko
type: Opaque
stringData:
  accessKeyId: <vm-images-cdi-reader access key>
  secretKey: <vm-images-cdi-reader secret key>
```

Then import the qcow2 into a root PVC:

```yaml
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: gecko-root
  namespace: gecko
spec:
  source:
    s3:
      url: "https://vm-images-s3.allegedly.works/vm-images/bootstrap/<commit>.qcow2"
      secretRef: gecko-vm-images-s3-reader
  pvc:
    accessModes:
      - ReadWriteOnce
    resources:
      requests:
        storage: 20Gi
```

After import, boot the VM from `gecko-root`, SSH in, and switch to the real host
config:

```bash
sudo nixos-rebuild switch --flake github:agentydragon/ducktape?ref=devel#gecko
```

## Paving Notes

- The `vm-images` Bucket must exist before the public gateway starts. SeaweedFS
  can auto-create bucket directories from identity actions, which bypasses the
  Bucket CR adoption path. The Flux wiring applies `seaweedfs-vm-images-bucket`
  first and gates `seaweedfs-vm-images-s3` on it.
- New SeaweedFS collections need free logical volume slots on enough volume
  servers to satisfy `defaultReplication: "001"`. The bootstrap publish path
  exposed this when the old 30GB `volumeSizeLimitMB` left two volume servers at
  their computed 61/61 slot limit before `vm-images` had any writable volumes.
  Keep the lower 16GB limit unless the volume-server capacity model changes.
- The public `vm-images-s3` HTTPRoute must allow long request and backend
  request timeouts. GitHub-hosted runners can upload the 5.6 GiB bootstrap qcow2
  slowly, and Envoy's default stream timeouts cut multipart PUT request bodies
  before SeaweedFS can finish reading each part.
- The first manual spike created `vm-images-s3-credentials` directly and was
  removed. The paved path is SOPS -> Flux -> Kubernetes Secret -> ExternalSecret
  rendered gateway config.
- The dedicated gateway runs as non-root and uses the restricted PodSecurity
  settings expected by current namespace admission.
