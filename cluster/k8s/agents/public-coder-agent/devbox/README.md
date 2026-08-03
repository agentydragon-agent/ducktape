# public-coder-devbox

Dedicated NixOS/KubeVirt build and test VM for the `public-coder-agent`
OpenClaw instance.

## Access

The VM is not exposed on a public port. OpenClaw reaches SSH through the
ClusterIP Service:

```text
public-coder-devbox-ssh.public-coder-agent.svc.cluster.local:22
```

The OpenClaw Deployment exposes the matching SSH key and config read-only at
`/run/secrets/public-coder-devbox-ssh`. Kubernetes Secret volumes are root-owned
and group-readable, which OpenSSH correctly rejects for a private key. Copy the
files into the agent's writable home with strict permissions before connecting:

```bash
install -d -m 0700 ~/.ssh
install -m 0600 /run/secrets/public-coder-devbox-ssh/id_ed25519 ~/.ssh/id_ed25519
install -m 0644 /run/secrets/public-coder-devbox-ssh/known_hosts ~/.ssh/known_hosts
install -m 0644 /run/secrets/public-coder-devbox-ssh/config ~/.ssh/config
```

The normal command is then:

```bash
ssh public-coder-devbox
```

## Egress and trust

The KubeVirt `virt-launcher` Pod is selected by a CiliumClusterwideNetworkPolicy
that permits only CoreDNS and the `public-coder-agent` iron-proxy. The guest's
HTTP(S) proxy variables point at that Service, but the network policy is the
actual enforcement layer.

The interception CA is deliberately not copied into this repository. The
existing trust-manager Bundle publishes the live CA bundle into the shared
`public-coder-agent` namespace as `ConfigMap/public-coder-agent-proxy-ca-cert`.
KubeVirt attaches that ConfigMap as a read-only virtio disk; the NixOS service
mounts it at boot and assembles the runtime CA bundle. CA rotation therefore
follows the declarative cert-manager/trust-manager resources without a
certificate being committed here.

The persistent SSH host key is a separate SOPS-encrypted Secret attached as a
KubeVirt disk. The image's systemd first-boot unit consumes that disk directly,
so no composed cloud-init blob is needed for the devbox.

## Why this VM exists

The OpenClaw container keeps its workspace and runtime local, but it does not
have the full NixOS/Bazel/BuildBuddy toolchain needed for Ducktape development.
This separate VM provides that toolchain without making the OpenClaw image
larger or coupling its lifecycle to the build environment. It is deliberately
private, disposable, and GitOps-managed rather than a second personal
workstation.

## How it works

- **KubeVirt + CDI:** Flux manages the VM and its persistent root DataVolume.
  The DataVolume imports a commit-addressed qcow2 from the in-cluster S3
  publisher, so rebuilding an image never mutates an existing disk in place.
- **Purpose-built image:** `.#public-coder-devbox-image` contains the complete
  NixOS and Home Manager build/test configuration. No first-boot
  `nixos-rebuild` or cloud-init step is required.
- **Stable SSH identity:** A SOPS-encrypted host-key Secret is attached as a
  read-only virtio disk. A first-boot systemd unit installs that key before
  `sshd` starts, keeping the service key stable across VM recreation.
- **Proxy trust:** A trust-manager CA ConfigMap is attached as a read-only
  virtio disk. Another systemd unit assembles the runtime CA bundle. Proxy
  variables are configured for login shells and explicitly for `nix-daemon`;
  Nix uses the assembled CA through `ssl-cert-file`/`NIX_SSL_CERT_FILE`.
- **Egress boundary:** Cilium permits the virt-launcher Pod to reach only DNS
  and the `public-coder-agent` iron-proxy. Guest proxy settings are necessary
  for applications, but the network policy is the actual security boundary.

## Updating the image

The in-cluster `vm-images-publisher` builds and uploads the selected flake
output with these settings:

```text
IMAGE_OUTPUT=public-coder-devbox-image
OBJECT_PREFIX=public-coder-devbox
```

The resulting object is named `public-coder-devbox/<git-sha>.qcow2`. A GitOps
change then pins the VM manifest to that exact object. For a new disk, use a
new DataVolume name or recreate the VM: CDI treats an already-succeeded
DataVolume as immutable and will not re-import it merely because its S3 URL
changed.
