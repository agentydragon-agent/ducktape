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

## Bootstrap and switch

The VM is built from the purpose-specific `.#public-coder-devbox-image`
output. The image already contains the full NixOS and Home Manager build/test
configuration, so no first-boot `nixos-rebuild` is needed.

At boot, a NixOS systemd unit mounts the SOPS-provided host-key disk and installs
its persisted host key before `sshd` starts. A second unit mounts the live proxy
CA ConfigMap disk and assembles the runtime CA bundle. SSH authorized keys,
proxy variables, and Nix proxy settings are part of the image configuration.

The root disk is persistent, so subsequent boots use the same declarative
configuration directly. The generic bootstrap image remains available for
other VMs that intentionally use the manual-switch workflow.

## Image publication

Build and publish the image from the in-cluster `vm-images-publisher`:

```bash
job_name="publish-devbox-$(date +%s)"
kubectl create job --from=cronjob/vm-images-publisher "$job_name" \
  -n vm-images-publisher
kubectl -n vm-images-publisher set env "job/$job_name" \
  IMAGE_OUTPUT=public-coder-devbox-image OBJECT_PREFIX=public-coder-devbox
```

After publication, update the VM's root S3 URL to
`public-coder-devbox/<sha>.qcow2`. The VM
manifest can then drop the cloud-init disk and Secret entirely; only the
persisted host-key and proxy-CA virtio disks remain.
