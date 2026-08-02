# public-coder-devbox

Dedicated NixOS/KubeVirt build and test VM for the `public-coder-agent`
OpenClaw instance.

## Access

The VM is not exposed on a public port. OpenClaw reaches SSH through the
ClusterIP Service:

```text
public-coder-devbox-ssh.public-coder-agent.svc.cluster.local:22
```

The OpenClaw Deployment mounts the matching SSH key and config as
`public-coder-devbox`, so the normal command is:

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

The cloud-init recipe is non-secret and lives inline in the VM manifest. The
only secret input to it — the persistent SSH host key — is a separate
SOPS-encrypted Secret attached as another KubeVirt disk. This keeps the
cloud-init drive reproducible from its inputs instead of storing a composed
opaque blob.

## Bootstrap and switch

The VM starts from the existing minimal bootstrap qcow2. Its inline cloud-init
recipe mounts the SOPS-provided host-key disk, installs root's authorized key,
and sets the proxy/CA settings needed for the first manual switch. After the VM
is reachable, run:

```text
nixos-rebuild switch --flake github:agentydragon/ducktape?ref=devel#public-coder-devbox
```

The root disk is persistent, so subsequent boots use the switched NixOS
configuration directly. Keeping the switch manual makes the bootstrap failure
mode easy to inspect and avoids hiding a failed first deployment in cloud-init.
